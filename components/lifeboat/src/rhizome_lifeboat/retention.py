from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .checkpoint import verify_checkpoint
from .config import Config
from .util import (
    atomic_write,
    canonical_json_bytes,
    exclusive_lock,
    fsync_directory,
    utc_now,
    validate_store,
)


RETENTION_SCHEMA = "rhizome-lifeboat-retention-v1"
CHECKPOINT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{10}$")
DISABLE_MARKER = "RETENTION_DISABLED"


def _created_at(record: dict[str, Any]) -> datetime:
    value = datetime.fromisoformat(record["created_at"])
    if value.tzinfo is None:
        raise ValueError(f"checkpoint timestamp is not timezone-aware: {record['checkpoint_id']}")
    return value.astimezone(UTC)


def select_retention(
    records: list[dict[str, Any]],
    pinned_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Select 3 UTC days, 2 older ISO weeks and 1 older UTC month.

    Only verified records are eligible for deletion. Active references are
    additional pins outside the six policy slots. With too little calendar
    history, redundant same-day points are still bounded while the newest and
    one older verified fallback remain protected.
    """
    pinned = pinned_ids or set()
    verified = sorted(
        (record for record in records if record.get("status") == "verified"),
        key=_created_at,
        reverse=True,
    )
    keep: dict[str, list[str]] = {}

    def retain(record: dict[str, Any], reason: str) -> None:
        keep.setdefault(record["checkpoint_id"], []).append(reason)

    daily_dates: set[tuple[int, int, int]] = set()
    for record in verified:
        stamp = _created_at(record)
        day = (stamp.year, stamp.month, stamp.day)
        if day in daily_dates:
            continue
        retain(record, f"daily:{stamp.date().isoformat()}")
        daily_dates.add(day)
        if len(daily_dates) == 3:
            break

    represented_weeks = {
        _created_at(record).isocalendar()[:2]
        for record in verified
        if record["checkpoint_id"] in keep
    }
    weekly_count = 0
    for record in verified:
        if record["checkpoint_id"] in keep:
            continue
        stamp = _created_at(record)
        week = stamp.isocalendar()[:2]
        if week in represented_weeks:
            continue
        retain(record, f"weekly:{week[0]}-W{week[1]:02d}")
        represented_weeks.add(week)
        weekly_count += 1
        if weekly_count == 2:
            break

    represented_months = {
        (_created_at(record).year, _created_at(record).month)
        for record in verified
        if record["checkpoint_id"] in keep
    }
    for record in verified:
        if record["checkpoint_id"] in keep:
            continue
        stamp = _created_at(record)
        month = (stamp.year, stamp.month)
        if month in represented_months:
            continue
        retain(record, f"monthly:{stamp.year}-{stamp.month:02d}")
        break

    # One recovery point is not a recovery strategy. When calendar history is
    # sparse, retain the oldest verified point as the independent fallback.
    if len(keep) < 2 and len(verified) > 1:
        retain(verified[-1], "fallback:oldest-verified")

    by_id = {record["checkpoint_id"]: record for record in verified}
    missing_pins: list[str] = []
    for checkpoint_id in sorted(pinned):
        if checkpoint_id in by_id:
            retain(by_id[checkpoint_id], "pin:active-recovery-reference")
        else:
            missing_pins.append(checkpoint_id)

    retained = [
        {**record, "retention_reasons": keep[record["checkpoint_id"]]}
        for record in verified
        if record["checkpoint_id"] in keep
    ]
    deleted = []
    retained_days = {
        _created_at(record).date()
        for record in retained
        if any(reason.startswith("daily:") for reason in record["retention_reasons"])
    }
    for record in verified:
        if record["checkpoint_id"] in keep:
            continue
        stamp = _created_at(record)
        reason = (
            "redundant verified checkpoint on a retained UTC day"
            if stamp.date() in retained_days
            else "outside the 3 daily / 2 weekly / 1 monthly calendar slots"
        )
        deleted.append({**record, "deletion_reason": reason})

    preserved = [
        record for record in records if record.get("status") != "verified"
    ]
    return {
        "retained": retained,
        "delete": deleted,
        "preserved_non_candidates": preserved,
        "missing_active_references": missing_pins,
    }


def _assert_safe_checkpoint_tree(checkpoints: Path, checkpoint: Path) -> None:
    if not CHECKPOINT_ID.fullmatch(checkpoint.name):
        raise RuntimeError(f"unsafe checkpoint name: {checkpoint.name}")
    root = checkpoints.resolve(strict=True)
    info = checkpoint.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"checkpoint is not a real directory: {checkpoint}")
    if checkpoint.resolve(strict=True).parent != root:
        raise RuntimeError(f"checkpoint escapes the designated store: {checkpoint}")
    for directory, names, files in os.walk(checkpoint, followlinks=False):
        base = Path(directory)
        for name in (*names, *files):
            path = base / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise RuntimeError(f"unsafe checkpoint entry: {path}")


def _tree_size(path: Path) -> int:
    total = path.lstat().st_size
    for directory, names, files in os.walk(path, followlinks=False):
        base = Path(directory)
        for name in (*names, *files):
            total += (base / name).lstat().st_size
    return total


def inventory_checkpoints(config: Config) -> list[dict[str, Any]]:
    checkpoints = config.store.root / "checkpoints"
    records: list[dict[str, Any]] = []
    for path in sorted(checkpoints.iterdir(), key=lambda item: item.name, reverse=True):
        if path.name.startswith("."):
            records.append({
                "checkpoint_id": path.name,
                "status": "ambiguous",
                "reason": "hidden partial or interrupted maintenance entry; preserved",
                "size_bytes": None,
            })
            continue
        try:
            _assert_safe_checkpoint_tree(checkpoints, path)
            verified = verify_checkpoint(config, path.name)
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            records.append({
                **verified,
                "kind": manifest.get("kind"),
                "reason": manifest.get("reason"),
                "size_bytes": _tree_size(path),
            })
        except Exception as error:
            records.append({
                "checkpoint_id": path.name,
                "status": "invalid",
                "error": f"{type(error).__name__}: {error}",
                "size_bytes": None,
            })
    return records


def _active_references(
    config: Config,
    ignore_retention_transaction: str | None = None,
) -> tuple[set[str], list[str]]:
    references: set[str] = set()
    errors: list[str] = []
    window_path = config.store.root / "state" / "change-window.json"
    if window_path.exists():
        try:
            window = json.loads(window_path.read_text(encoding="utf-8"))
            if window.get("status") == "open" and isinstance(window.get("checkpoint_id"), str):
                references.add(window["checkpoint_id"])
        except Exception as error:
            errors.append(f"cannot validate change-window metadata: {error}")

    receipts = config.store.root / "receipts"
    for path in sorted(receipts.glob("*.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"cannot validate receipt metadata {path.name}: {error}")
            continue
        if receipt.get("outcome") == "in-progress" and isinstance(receipt.get("checkpoint_id"), str):
            references.add(receipt["checkpoint_id"])
        if (
            receipt.get("schema") == RETENTION_SCHEMA
            and receipt.get("outcome") != "completed"
            and receipt.get("transaction_id") != ignore_retention_transaction
        ):
            errors.append(f"unfinished retention transaction: {path.name}")
    return references, errors


def _lock_context(config: Config, assume_locked: bool) -> Iterator[None]:
    if assume_locked:
        return contextlib.nullcontext()
    return exclusive_lock(config.store.root / "locks" / "controller.lock")


def retention_plan(config: Config) -> dict[str, Any]:
    volume = validate_store(
        config.store.root,
        config.store.mountpoint,
        config.store.minimum_free_bytes,
        config.store.require_mountpoint,
        config.store.expected_mount_source,
        config.store.expected_filesystem,
    )
    records = inventory_checkpoints(config)
    references, metadata_errors = _active_references(config)
    selected = select_retention(records, references)
    invalid = [record for record in records if record.get("status") == "invalid"]
    blockers = list(metadata_errors)
    if invalid:
        blockers.append("one or more visible checkpoint candidates failed validation")
    if selected["missing_active_references"]:
        blockers.append("an active recovery reference does not resolve to a verified checkpoint")
    return {
        "schema": RETENTION_SCHEMA,
        "status": "blocked" if blockers else "dry-run",
        "generated_at": utc_now(),
        "policy": {"daily": 3, "weekly": 2, "monthly": 1, "timezone": "UTC"},
        "enabled": config.retention.enabled,
        "disable_marker": str(config.store.root / "state" / DISABLE_MARKER),
        "disabled_by_marker": (config.store.root / "state" / DISABLE_MARKER).exists(),
        "volume": volume,
        "active_references": sorted(references),
        "blockers": blockers,
        **selected,
    }


def prune_checkpoints(
    config: Config,
    *,
    dry_run: bool,
    required_new_checkpoint_id: str | None = None,
    expected_delete_ids: set[str] | None = None,
    assume_locked: bool = False,
    fail_after_stage: bool = False,
) -> dict[str, Any]:
    """Plan retention or delete only after a newly verified checkpoint.

    ``fail_after_stage`` is an unexposed test failpoint used to prove that an
    interrupted atomic staging step leaves a receipt and blocks later pruning.
    """
    with _lock_context(config, assume_locked):
        plan = retention_plan(config)
        if dry_run:
            return plan
        if not config.retention.enabled:
            return {**plan, "status": "disabled", "delete": []}
        if plan["disabled_by_marker"]:
            return {**plan, "status": "disabled", "delete": []}
        if plan["blockers"]:
            raise RuntimeError("retention blocked: " + "; ".join(plan["blockers"]))
        if required_new_checkpoint_id is None:
            raise RuntimeError("pruning is permitted only after a newly verified checkpoint")
        verified_ids = [record["checkpoint_id"] for record in plan["retained"] + plan["delete"]]
        if required_new_checkpoint_id not in verified_ids:
            raise RuntimeError("new checkpoint is not verified in the retention inventory")
        newest = max(
            (record for record in plan["retained"] + plan["delete"]),
            key=_created_at,
        )["checkpoint_id"]
        if newest != required_new_checkpoint_id:
            raise RuntimeError("required checkpoint is not the latest verified recovery point")
        actual_delete_ids = {record["checkpoint_id"] for record in plan["delete"]}
        if expected_delete_ids is not None and actual_delete_ids != expected_delete_ids:
            raise RuntimeError(
                "approved deletion set changed: "
                f"expected {sorted(expected_delete_ids)}, got {sorted(actual_delete_ids)}"
            )
        if not plan["delete"]:
            return {**plan, "status": "completed", "deleted": []}

        transaction_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        receipt_path = config.store.root / "receipts" / f"retention-{transaction_id}.json"
        receipt: dict[str, Any] = {
            "schema": RETENTION_SCHEMA,
            "transaction_id": transaction_id,
            "started_at": utc_now(),
            "outcome": "in-progress",
            "policy": plan["policy"],
            "required_new_checkpoint_id": required_new_checkpoint_id,
            "retained": plan["retained"],
            "deletions": [],
        }
        atomic_write(receipt_path, canonical_json_bytes(receipt))
        checkpoints = config.store.root / "checkpoints"
        try:
            for candidate in plan["delete"]:
                checkpoint_id = candidate["checkpoint_id"]
                references, errors = _active_references(
                    config,
                    ignore_retention_transaction=transaction_id,
                )
                if errors:
                    raise RuntimeError("retention metadata changed: " + "; ".join(errors))
                if checkpoint_id in references:
                    raise RuntimeError(f"checkpoint became actively referenced: {checkpoint_id}")
                path = checkpoints / checkpoint_id
                _assert_safe_checkpoint_tree(checkpoints, path)
                verified = verify_checkpoint(config, checkpoint_id)
                if verified["manifest_sha256"] != candidate["manifest_sha256"]:
                    raise RuntimeError(f"checkpoint manifest changed: {checkpoint_id}")
                action = {
                    "checkpoint_id": checkpoint_id,
                    "size_bytes": candidate["size_bytes"],
                    "reason": candidate["deletion_reason"],
                    "manifest_sha256": verified["manifest_sha256"],
                    "verified_at": utc_now(),
                    "status": "staging",
                }
                receipt["deletions"].append(action)
                atomic_write(receipt_path, canonical_json_bytes(receipt))
                staged = checkpoints / f".pruning-{checkpoint_id}-{transaction_id}"
                os.replace(path, staged)
                fsync_directory(checkpoints)
                action["status"] = "staged"
                action["staged_path"] = str(staged)
                atomic_write(receipt_path, canonical_json_bytes(receipt))
                if fail_after_stage:
                    raise RuntimeError("deliberate interrupted-pruning failpoint")
                shutil.rmtree(staged)
                fsync_directory(checkpoints)
                action["status"] = "deleted"
                action["deleted_at"] = utc_now()
                atomic_write(receipt_path, canonical_json_bytes(receipt))
            receipt["outcome"] = "completed"
            receipt["completed_at"] = utc_now()
            atomic_write(receipt_path, canonical_json_bytes(receipt))
        except BaseException as error:
            receipt["outcome"] = "interrupted"
            receipt["error"] = f"{type(error).__name__}: {error}"
            receipt["interrupted_at"] = utc_now()
            atomic_write(receipt_path, canonical_json_bytes(receipt))
            raise
        return {**plan, "status": "completed", "deleted": receipt["deletions"], "receipt": str(receipt_path)}
