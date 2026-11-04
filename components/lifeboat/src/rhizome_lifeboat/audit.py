from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .checkpoint import GNU_TAR, _excluded, sqlite_details
from .config import Config
from .util import mount_info, utc_now, validate_store_mount


def _tree_audit(source: Path, exclude: tuple[str, ...]) -> dict[str, Any]:
    entries = 0
    regular_bytes = 0
    skipped = 0
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _excluded(relative, exclude) or any(
            _excluded(parent, exclude) for parent in relative.parents if str(parent) != "."
        ):
            skipped += 1
            continue
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise RuntimeError(f"unsupported tree entry: {path}")
        lowered = relative.name.lower()
        if stat.S_ISREG(info.st_mode) and (".sqlite" in lowered or lowered.endswith(("-wal", "-shm"))):
            raise RuntimeError(f"SQLite-like file is not separately protected or excluded: {path}")
        if stat.S_ISREG(info.st_mode):
            regular_bytes += info.st_size
        entries += 1
    return {"entries": entries, "regular_bytes": regular_bytes, "excluded_entries": skipped}


def audit_config(config: Config) -> dict[str, Any]:
    if not GNU_TAR.is_file() or not os.access(GNU_TAR, os.X_OK):
        raise RuntimeError(f"required GNU tar executable is unavailable: {GNU_TAR}")
    volume = validate_store_mount(
        config.store.mountpoint,
        config.store.root,
        config.store.minimum_free_bytes,
        config.store.require_mountpoint,
        config.store.expected_mount_source,
        config.store.expected_filesystem,
    )
    items: list[dict[str, Any]] = []
    estimated_bytes = 0
    for spec in config.files:
        if not spec.source.is_file() or spec.source.is_symlink():
            if spec.required:
                raise RuntimeError(f"required file is unavailable: {spec.source}")
            continue
        size = spec.source.stat().st_size
        estimated_bytes += size
        items.append({"name": spec.name, "kind": "file", "size": size})
    for spec in config.databases:
        if not spec.source.is_file():
            if spec.required:
                raise RuntimeError(f"required database is unavailable: {spec.source}")
            continue
        details = sqlite_details(spec.source)
        if spec.expected_user_version is not None and details["user_version"] != spec.expected_user_version:
            raise RuntimeError(f"{spec.name} user_version mismatch")
        if spec.expected_schema_sha256 and details["schema_sha256"] != spec.expected_schema_sha256:
            raise RuntimeError(f"{spec.name} schema fingerprint mismatch")
        size = spec.source.stat().st_size
        estimated_bytes += size
        items.append({"name": spec.name, "kind": "sqlite", "size": size, "sqlite": details})
    for spec in config.trees:
        if not spec.source.is_dir() or spec.source.is_symlink():
            if spec.required:
                raise RuntimeError(f"required tree is unavailable: {spec.source}")
            continue
        details = _tree_audit(spec.source, spec.exclude)
        estimated_bytes += details["regular_bytes"]
        items.append({"name": spec.name, "kind": "tree", **details})
    for spec in config.symlinks:
        if not spec.source.is_symlink():
            if spec.required:
                raise RuntimeError(f"required symlink is unavailable: {spec.source}")
            continue
        target = os.readlink(spec.source)
        items.append({"name": spec.name, "kind": "symlink", "target": target})
    return {
        "status": "audited",
        "checked_at": utc_now(),
        "application": {
            "name": config.application.name,
            "version": config.application.version,
            "revision": config.application.revision,
        },
        "store_volume": volume,
        "store_exists": config.store.root.exists(),
        "estimated_checkpoint_bytes": estimated_bytes,
        "items": items,
    }
