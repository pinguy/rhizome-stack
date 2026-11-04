from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path
from typing import Any

from .checkpoint import sqlite_details, verify_checkpoint
from .config import Config
from .util import atomic_write, canonical_json_bytes, sha256_file, utc_now


DRILL_SCHEMA = "rhizome-lifeboat-restore-drill-v1"


def _mapped(destination: Path, original: str) -> Path:
    source = Path(original)
    if not source.is_absolute():
        raise RuntimeError(f"restore path is not absolute: {original}")
    return destination / source.relative_to("/")


def restore_drill(config: Config, checkpoint_id: str, destination: Path) -> dict[str, Any]:
    """Materialise a checkpoint below a disposable root without touching live paths."""
    if not destination.is_absolute():
        raise ValueError("drill destination must be absolute")
    if destination.exists():
        raise FileExistsError(destination)
    verify_checkpoint(config, checkpoint_id)
    checkpoint = config.store.root / "checkpoints" / checkpoint_id
    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, mode=0o700)
    restored: list[dict[str, Any]] = []
    try:
        ordered_items = sorted(
            manifest["items"],
            key=lambda item: {"tree": 0, "file": 1, "sqlite": 2, "symlink": 3}[item["kind"]],
        )
        for item in ordered_items:
            if item.get("missing"):
                continue
            target = _mapped(destination, item["restore"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if item["kind"] == "symlink":
                os.symlink(item["link_target"], target)
                digest = hashlib.sha256(os.readlink(target).encode()).hexdigest()
                if digest != item["sha256"]:
                    raise RuntimeError(f"drill symlink mismatch: {item['name']}")
                restored.append({"name": item["name"], "kind": "symlink", "target": str(target)})
                continue
            artifact = checkpoint / item["artifact"]
            if item["kind"] == "tree":
                target.mkdir()
                with tarfile.open(artifact, "r") as archive:
                    archive.extractall(target, filter="data")
                member_count = sum(1 for _ in target.rglob("*"))
                if member_count != item["tree"]["members"]:
                    raise RuntimeError(f"drill tree member count mismatch: {item['name']}")
                restored.append({
                    "name": item["name"], "kind": "tree", "target": str(target),
                    "members": member_count,
                })
                continue
            shutil.copy2(artifact, target)
            if sha256_file(target) != item["sha256"]:
                raise RuntimeError(f"drill file hash mismatch: {item['name']}")
            record: dict[str, Any] = {"name": item["name"], "kind": item["kind"], "target": str(target)}
            if item["kind"] == "sqlite":
                details = sqlite_details(target)
                if details["quick_check"] != "ok" or details["schema_sha256"] != item["sqlite"]["schema_sha256"]:
                    raise RuntimeError(f"drill database verification failed: {item['name']}")
                record["sqlite"] = details
            restored.append(record)
        receipt = {
            "schema": DRILL_SCHEMA,
            "status": "passed",
            "completed_at": utc_now(),
            "checkpoint_id": checkpoint_id,
            "destination": str(destination),
            "items_restored": len(restored),
            "items": restored,
        }
        atomic_write(destination / "RESTORE-DRILL.json", canonical_json_bytes(receipt), mode=0o600)
        return receipt
    except BaseException as error:
        atomic_write(
            destination / "RESTORE-DRILL-FAILED.json",
            canonical_json_bytes({
                "schema": DRILL_SCHEMA,
                "status": "failed",
                "failed_at": utc_now(),
                "checkpoint_id": checkpoint_id,
                "error": f"{type(error).__name__}: {error}",
            }),
            mode=0o600,
        )
        raise
