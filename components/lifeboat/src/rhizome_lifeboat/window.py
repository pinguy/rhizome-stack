from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .checkpoint import create_checkpoint, verify_checkpoint
from .config import Config
from .util import atomic_write, canonical_json_bytes, utc_now
from .health import wait_until_healthy


WINDOW_SCHEMA = "rhizome-lifeboat-change-window-v1"


def _state_path(config: Config) -> Path:
    return config.store.root / "state" / "change-window.json"


def load_window(config: Config) -> dict[str, Any] | None:
    path = _state_path(config)
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema") != WINDOW_SCHEMA:
        raise RuntimeError("unsupported change-window state")
    return state


def write_window(config: Config, state: dict[str, Any]) -> None:
    atomic_write(_state_path(config), canonical_json_bytes(state), mode=0o600)


def open_window(config: Config, checkpoint_id: str, reason: str) -> dict[str, Any]:
    verified = verify_checkpoint(config, checkpoint_id)
    opened = datetime.now(UTC)
    state = {
        "schema": WINDOW_SCHEMA,
        "status": "open",
        "reason": reason,
        "checkpoint_id": checkpoint_id,
        "checkpoint_manifest_sha256": verified["manifest_sha256"],
        "opened_at": opened.isoformat(timespec="seconds"),
        "expires_at": (opened + timedelta(seconds=config.policy.change_window_seconds)).isoformat(
            timespec="seconds"
        ),
        "automatic_rollbacks_attempted": 0,
        "maximum_automatic_rollbacks": config.policy.maximum_automatic_rollbacks,
    }
    write_window(config, state)
    return state


def prepare_change(config: Config, reason: str) -> dict[str, Any]:
    if not config.service.stop_command or not config.service.start_command:
        raise RuntimeError("coordinated pre-change checkpoint requires fixed stop/start commands")
    stopped = subprocess.run(
        config.service.stop_command,
        capture_output=True,
        text=True,
        timeout=config.service.command_timeout_seconds,
        check=False,
    )
    if stopped.returncode != 0:
        raise RuntimeError(f"could not stop service for coordinated checkpoint: {stopped.stderr.strip()}")
    checkpoint: dict[str, Any] | None = None
    checkpoint_error: BaseException | None = None
    try:
        checkpoint = create_checkpoint(config, reason, "pre-change")
    except BaseException as error:
        checkpoint_error = error
    started = subprocess.run(
        config.service.start_command,
        capture_output=True,
        text=True,
        timeout=config.service.command_timeout_seconds,
        check=False,
    )
    if started.returncode != 0:
        raise RuntimeError(f"could not restart service after coordinated checkpoint: {started.stderr.strip()}")
    health = wait_until_healthy(config)
    if not health.healthy:
        raise RuntimeError(f"service failed after coordinated checkpoint: {health.failure_class}")
    if checkpoint_error is not None:
        raise checkpoint_error
    assert checkpoint is not None
    window = open_window(config, checkpoint["checkpoint_id"], reason)
    return {
        "checkpoint": checkpoint,
        "window": window,
        "coordination": {
            "service_stopped": True,
            "service_restarted": True,
            "post_checkpoint_health": health.as_dict(),
        },
    }


def window_eligibility(config: Config) -> tuple[bool, str, dict[str, Any] | None]:
    state = load_window(config)
    if state is None:
        return False, "no recorded change window", None
    if state.get("status") != "open":
        return False, f"change window is {state.get('status')}", state
    expires = datetime.fromisoformat(state["expires_at"])
    if datetime.now(UTC) >= expires:
        state["status"] = "expired"
        state["closed_at"] = utc_now()
        write_window(config, state)
        return False, "change window has expired", state
    if int(state["automatic_rollbacks_attempted"]) >= int(state["maximum_automatic_rollbacks"]):
        return False, "automatic rollback limit exhausted", state
    return True, "eligible", state


def claim_rollback(config: Config, incident_id: str) -> dict[str, Any]:
    eligible, reason, state = window_eligibility(config)
    if not eligible or state is None:
        raise RuntimeError(reason)
    state["automatic_rollbacks_attempted"] = int(state["automatic_rollbacks_attempted"]) + 1
    state["last_incident_id"] = incident_id
    state["last_attempt_claimed_at"] = utc_now()
    write_window(config, state)
    return state


def close_window(config: Config, outcome: str) -> dict[str, Any]:
    state = load_window(config)
    if state is None:
        raise RuntimeError("no change window to close")
    state["status"] = "closed"
    state["outcome"] = outcome
    state["closed_at"] = utc_now()
    write_window(config, state)
    return state
