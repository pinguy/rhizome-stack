from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .config import Config
from .util import utc_now
from .util import validate_store_mount


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    status_code: int | None = None
    payload: Any = None


@dataclass(frozen=True)
class Diagnosis:
    checked_at: str
    healthy: bool
    failure_class: str
    checks: tuple[CheckResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "healthy": self.healthy,
            "failure_class": self.failure_class,
            "checks": [asdict(check) for check in self.checks],
        }


def _run(command: tuple[str, ...], timeout: int) -> CheckResult:
    if not command:
        return CheckResult("service", False, "status command is not configured")
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckResult("service", False, f"status command failed: {error}")
    output = (completed.stdout + completed.stderr).strip()
    return CheckResult(
        "service",
        completed.returncode == 0,
        output or f"exit {completed.returncode}",
    )


def _json_get(base_url: str, path: str, timeout: float,
              token: str | None = None) -> tuple[int | None, Any, str]:
    request = urllib.request.Request(base_url.rstrip("/") + path)
    request.add_header("Accept", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            content_type = response.headers.get_content_type()
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as error:
        status = error.code
        content_type = error.headers.get_content_type() if error.headers else ""
        raw = error.read(1024 * 1024)
        error.close()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return None, None, str(error)
    if content_type != "application/json":
        return status, None, f"unexpected content type {content_type!r}"
    try:
        return status, json.loads(raw), ""
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return status, None, f"invalid JSON: {error}"


def _health_check(config: Config) -> CheckResult:
    status, payload, error = _json_get(
        config.health.base_url, config.health.health_path, config.health.timeout_seconds
    )
    ok = status == 200 and isinstance(payload, dict) and payload.get("ok") is True \
        and payload.get("status") == "live"
    return CheckResult("liveness", ok, error or ("live" if ok else "invalid liveness payload"), status, payload)


def _startup_check(config: Config, ready: CheckResult | None = None) -> CheckResult:
    if not config.health.startup_path:
        # This OpenClaw build has no /startupz. A separately-labelled fallback
        # is allowed only when the exact readiness payload has already passed.
        ok = bool(ready and ready.ok)
        return CheckResult(
            "startup",
            ok,
            "synthesised from validated readiness; native /startupz unavailable",
            ready.status_code if ready else None,
            ready.payload if ready else None,
        )
    status, payload, error = _json_get(
        config.health.base_url, config.health.startup_path, config.health.timeout_seconds
    )
    ok = status == 200 and isinstance(payload, dict) and (
        payload.get("started") is True or payload.get("status") in {"started", "ready"}
    )
    return CheckResult("startup", ok, error or ("started" if ok else "invalid startup payload"), status, payload)


def _ready_check(config: Config) -> CheckResult:
    status, payload, error = _json_get(
        config.health.base_url, config.health.ready_path, config.health.timeout_seconds
    )
    failing = payload.get("failing") if isinstance(payload, dict) else None
    ok = status == 200 and isinstance(payload, dict) and payload.get("ready") is True \
        and failing == []
    return CheckResult("readiness", ok, error or ("ready" if ok else "invalid readiness payload"), status, payload)


def _read_token(config: Config) -> tuple[str | None, str | None]:
    if config.health.token_file is None:
        return None, "functional probe token file is not configured"
    try:
        token = config.health.token_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        return None, f"cannot read functional probe token: {error}"
    if not token:
        return None, "functional probe token is empty"
    return token, None


def _functional_check(config: Config) -> CheckResult:
    token, token_error = _read_token(config)
    if token_error:
        return CheckResult("functional", False, token_error)
    status, payload, error = _json_get(
        config.health.base_url,
        config.health.functional_path,
        config.health.timeout_seconds,
        token,
    )
    models = payload.get("data") if isinstance(payload, dict) else None
    ok = status == 200 and isinstance(models, list) and len(models) >= config.health.required_model_count
    return CheckResult(
        "functional",
        ok,
        error or (f"{len(models)} models visible" if ok else "invalid functional payload"),
        status,
        payload,
    )


def _readiness_failure_class(check: CheckResult) -> str:
    material = json.dumps(check.payload, sort_keys=True).lower() if check.payload is not None else check.detail.lower()
    if any(word in material for word in ("sqlite", "database", "schema", "integrity", "admission")):
        return "DATABASE_ADMISSION_FAILURE"
    if any(word in material for word in ("config", "configuration", "parse", "invalid option")):
        return "CONFIG_ADMISSION_FAILURE"
    if any(word in material for word in ("telegram", "channel", "credential", "authentication", "unauthor")):
        return "CHANNEL_AUTH_FAILURE"
    if any(word in material for word in ("disk full", "no space", "filesystem", "read-only")):
        return "STORAGE_FAILURE"
    if any(word in material for word in ("model", "provider", "ollama", "nvidia", "openai")):
        return "PROVIDER_DEGRADED"
    return "READINESS_FAILURE"


def diagnose(config: Config) -> Diagnosis:
    checks: list[CheckResult] = []
    service = _run(config.service.status_command, config.service.command_timeout_seconds)
    checks.append(service)
    if not service.ok:
        return Diagnosis(utc_now(), False, "PROCESS_CRASH", tuple(checks))

    liveness = _health_check(config)
    checks.append(liveness)
    if not liveness.ok:
        return Diagnosis(utc_now(), False, "HTTP_LIVENESS_FAILURE", tuple(checks))

    readiness = _ready_check(config)
    # Native startup is checked before readiness; the current production build
    # explicitly configures no native path and uses the validated-ready fallback.
    startup = _startup_check(config, readiness)
    checks.append(startup)
    if not startup.ok:
        return Diagnosis(utc_now(), False, "STARTUP_INCOMPLETE", tuple(checks))

    checks.append(readiness)
    if not readiness.ok:
        return Diagnosis(utc_now(), False, _readiness_failure_class(readiness), tuple(checks))

    functional = _functional_check(config)
    checks.append(functional)
    if not functional.ok:
        failure = "FUNCTIONAL_AUTH_FAILURE" if functional.status_code in {401, 403} else "FUNCTIONAL_FAILURE"
        return Diagnosis(utc_now(), False, failure, tuple(checks))
    return Diagnosis(utc_now(), True, "HEALTHY", tuple(checks))


def wait_until_healthy(config: Config, timeout_seconds: int | None = None,
                       interval_seconds: float = 1.0) -> Diagnosis:
    deadline = time.monotonic() + (timeout_seconds or config.health.startup_grace_seconds)
    last = diagnose(config)
    while not last.healthy and time.monotonic() < deadline:
        time.sleep(interval_seconds)
        last = diagnose(config)
    return last


def monitor_probe(config: Config) -> dict[str, Any]:
    """Unprivileged Monit probe: volume, exact liveness, and readiness content."""
    checks: list[CheckResult] = []
    try:
        volume = validate_store_mount(
            config.store.mountpoint,
            config.store.root,
            config.store.minimum_free_bytes,
            config.store.require_mountpoint,
            config.store.expected_mount_source,
            config.store.expected_filesystem,
        )
        checks.append(CheckResult("backup-volume", True, "available", payload=volume))
    except Exception as error:
        checks.append(CheckResult("backup-volume", False, str(error)))
        return {
            "checked_at": utc_now(), "healthy": False, "failure_class": "BACKUP_VOLUME_FAILURE",
            "checks": [asdict(check) for check in checks],
        }
    liveness = _health_check(config)
    checks.append(liveness)
    if not liveness.ok:
        return {
            "checked_at": utc_now(), "healthy": False, "failure_class": "HTTP_LIVENESS_FAILURE",
            "checks": [asdict(check) for check in checks],
        }
    readiness = _ready_check(config)
    checks.append(readiness)
    return {
        "checked_at": utc_now(),
        "healthy": readiness.ok,
        "failure_class": "HEALTHY" if readiness.ok else _readiness_failure_class(readiness),
        "checks": [asdict(check) for check in checks],
    }
