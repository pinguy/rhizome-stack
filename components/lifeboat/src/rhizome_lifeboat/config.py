from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path
from typing import Any


@dataclasses.dataclass(frozen=True)
class StoreConfig:
    root: Path
    mountpoint: Path
    minimum_free_bytes: int = 1_073_741_824
    require_mountpoint: bool = False
    expected_mount_source: str | None = None
    expected_filesystem: str | None = None


@dataclasses.dataclass(frozen=True)
class ApplicationConfig:
    name: str
    version: str
    revision: str


@dataclasses.dataclass(frozen=True)
class FileSpec:
    name: str
    source: Path
    restore: Path
    required: bool = True


@dataclasses.dataclass(frozen=True)
class DatabaseSpec:
    name: str
    source: Path
    restore: Path
    required: bool = True
    expected_user_version: int | None = None
    expected_schema_sha256: str | None = None


@dataclasses.dataclass(frozen=True)
class TreeSpec:
    name: str
    source: Path
    restore: Path
    required: bool = True
    exclude: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class SymlinkSpec:
    name: str
    source: Path
    restore: Path
    required: bool = True


@dataclasses.dataclass(frozen=True)
class ServiceConfig:
    stop_command: tuple[str, ...] = ()
    start_command: tuple[str, ...] = ()
    status_command: tuple[str, ...] = ()
    journal_command: tuple[str, ...] = ()
    command_timeout_seconds: int = 30


@dataclasses.dataclass(frozen=True)
class HealthConfig:
    base_url: str = "http://127.0.0.1:18789"
    health_path: str = "/healthz"
    startup_path: str | None = "/startupz"
    ready_path: str = "/readyz"
    functional_path: str = "/v1/models"
    token_file: Path | None = None
    timeout_seconds: float = 5.0
    startup_grace_seconds: int = 60
    required_model_count: int = 1


@dataclasses.dataclass(frozen=True)
class PolicyConfig:
    change_window_seconds: int = 1800
    maximum_automatic_rollbacks: int = 1
    failure_confirmation_attempts: int = 3
    failure_confirmation_interval_seconds: float = 5.0
    automatic_failure_classes: tuple[str, ...] = (
        "PROCESS_CRASH",
        "CONFIG_ADMISSION_FAILURE",
        "DATABASE_ADMISSION_FAILURE",
    )


@dataclasses.dataclass(frozen=True)
class RetentionConfig:
    enabled: bool = False
    daily: int = 3
    weekly: int = 2
    monthly: int = 1


@dataclasses.dataclass(frozen=True)
class Config:
    path: Path
    store: StoreConfig
    application: ApplicationConfig
    files: tuple[FileSpec, ...]
    databases: tuple[DatabaseSpec, ...]
    trees: tuple[TreeSpec, ...]
    symlinks: tuple[SymlinkSpec, ...]
    service: ServiceConfig
    health: HealthConfig
    policy: PolicyConfig
    retention: RetentionConfig


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("command values must be arrays of strings")
    return tuple(value)


def _path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError(f"{field} must be an absolute path")
    return Path(value)


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    store_raw = raw.get("store", {})
    app_raw = raw.get("application", {})
    service_raw = raw.get("service", {})
    health_raw = raw.get("health", {})
    policy_raw = raw.get("policy", {})
    retention_raw = raw.get("retention", {})

    store = StoreConfig(
        root=_path(store_raw.get("root"), "store.root"),
        mountpoint=_path(store_raw.get("mountpoint"), "store.mountpoint"),
        minimum_free_bytes=int(store_raw.get("minimum_free_bytes", 1_073_741_824)),
        require_mountpoint=bool(store_raw.get("require_mountpoint", False)),
        expected_mount_source=store_raw.get("expected_mount_source"),
        expected_filesystem=store_raw.get("expected_filesystem"),
    )
    application = ApplicationConfig(
        name=str(app_raw.get("name", "OpenClaw")),
        version=str(app_raw.get("version", "unknown")),
        revision=str(app_raw.get("revision", "unknown")),
    )

    files = tuple(
        FileSpec(
            name=str(item["name"]),
            source=_path(item["source"], f"files.{item['name']}.source"),
            restore=_path(item.get("restore", item["source"]), f"files.{item['name']}.restore"),
            required=bool(item.get("required", True)),
        )
        for item in raw.get("files", [])
    )
    databases = tuple(
        DatabaseSpec(
            name=str(item["name"]),
            source=_path(item["source"], f"databases.{item['name']}.source"),
            restore=_path(item.get("restore", item["source"]), f"databases.{item['name']}.restore"),
            required=bool(item.get("required", True)),
            expected_user_version=(
                int(item["expected_user_version"])
                if "expected_user_version" in item
                else None
            ),
            expected_schema_sha256=item.get("expected_schema_sha256"),
        )
        for item in raw.get("databases", [])
    )
    trees = tuple(
        TreeSpec(
            name=str(item["name"]),
            source=_path(item["source"], f"trees.{item['name']}.source"),
            restore=_path(item.get("restore", item["source"]), f"trees.{item['name']}.restore"),
            required=bool(item.get("required", True)),
            exclude=tuple(str(pattern) for pattern in item.get("exclude", [])),
        )
        for item in raw.get("trees", [])
    )
    symlinks = tuple(
        SymlinkSpec(
            name=str(item["name"]),
            source=_path(item["source"], f"symlinks.{item['name']}.source"),
            restore=_path(item.get("restore", item["source"]), f"symlinks.{item['name']}.restore"),
            required=bool(item.get("required", True)),
        )
        for item in raw.get("symlinks", [])
    )
    service = ServiceConfig(
        stop_command=_tuple(service_raw.get("stop_command")),
        start_command=_tuple(service_raw.get("start_command")),
        status_command=_tuple(service_raw.get("status_command")),
        journal_command=_tuple(service_raw.get("journal_command")),
        command_timeout_seconds=int(service_raw.get("command_timeout_seconds", 30)),
    )
    token_value = health_raw.get("token_file")
    health = HealthConfig(
        base_url=str(health_raw.get("base_url", "http://127.0.0.1:18789")),
        health_path=str(health_raw.get("health_path", "/healthz")),
        startup_path=(
            str(health_raw["startup_path"]) if health_raw.get("startup_path") else None
        ),
        ready_path=str(health_raw.get("ready_path", "/readyz")),
        functional_path=str(health_raw.get("functional_path", "/v1/models")),
        token_file=_path(token_value, "health.token_file") if token_value else None,
        timeout_seconds=float(health_raw.get("timeout_seconds", 5.0)),
        startup_grace_seconds=int(health_raw.get("startup_grace_seconds", 60)),
        required_model_count=int(health_raw.get("required_model_count", 1)),
    )
    policy = PolicyConfig(
        change_window_seconds=int(policy_raw.get("change_window_seconds", 1800)),
        maximum_automatic_rollbacks=int(policy_raw.get("maximum_automatic_rollbacks", 1)),
        failure_confirmation_attempts=int(policy_raw.get("failure_confirmation_attempts", 3)),
        failure_confirmation_interval_seconds=float(
            policy_raw.get("failure_confirmation_interval_seconds", 5.0)
        ),
        automatic_failure_classes=tuple(
            str(item) for item in policy_raw.get(
                "automatic_failure_classes", PolicyConfig.automatic_failure_classes
            )
        ),
    )
    retention = RetentionConfig(
        enabled=bool(retention_raw.get("enabled", False)),
        daily=int(retention_raw.get("daily", 3)),
        weekly=int(retention_raw.get("weekly", 2)),
        monthly=int(retention_raw.get("monthly", 1)),
    )

    names = [item.name for item in (*files, *databases, *trees, *symlinks)]
    if len(names) != len(set(names)):
        raise ValueError("checkpoint item names must be unique")
    if not files and not databases and not trees and not symlinks:
        raise ValueError("at least one file or database must be configured")
    if policy.maximum_automatic_rollbacks < 0:
        raise ValueError("maximum_automatic_rollbacks cannot be negative")
    if policy.failure_confirmation_attempts < 1:
        raise ValueError("failure_confirmation_attempts must be at least one")
    if (retention.daily, retention.weekly, retention.monthly) != (3, 2, 1):
        raise ValueError("retention policy must be exactly 3 daily, 2 weekly and 1 monthly")

    return Config(
        path=config_path,
        store=store,
        application=application,
        files=files,
        databases=databases,
        trees=trees,
        symlinks=symlinks,
        service=service,
        health=health,
        policy=policy,
        retention=retention,
    )
