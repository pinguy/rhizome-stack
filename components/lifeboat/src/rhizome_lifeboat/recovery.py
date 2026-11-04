from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checkpoint import verify_checkpoint
from .config import Config
from .health import Diagnosis, diagnose, wait_until_healthy
from .util import (
    atomic_write,
    canonical_json_bytes,
    ensure_store_layout,
    exclusive_lock,
    fsync_directory,
    sha256_file,
    utc_now,
    validate_store,
    validate_store_mount,
)
from .window import claim_rollback, close_window, window_eligibility


RECEIPT_SCHEMA = "rhizome-lifeboat-recovery-receipt-v1"


def _run(command: tuple[str, ...], timeout: int, required: bool = True) -> dict[str, Any]:
    if not command:
        if required:
            raise RuntimeError("required service command is not configured")
        return {"command": [], "returncode": None, "stdout": "", "stderr": ""}
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if required:
            raise RuntimeError(f"command failed: {command!r}: {error}") from error
        return {"command": list(command), "returncode": None, "stdout": "", "stderr": str(error)}
    record = {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout[-131072:],
        "stderr": result.stderr[-131072:],
    }
    if required and result.returncode != 0:
        raise RuntimeError(f"command exited {result.returncode}: {command!r}: {result.stderr.strip()}")
    return record


def _confirm_failure(config: Config) -> Diagnosis:
    first = diagnose(config)
    if first.healthy:
        return first
    expected = first.failure_class
    consecutive = 1
    latest = first
    for _ in range(1, config.policy.failure_confirmation_attempts):
        time.sleep(config.policy.failure_confirmation_interval_seconds)
        latest = diagnose(config)
        if latest.healthy:
            return latest
        if latest.failure_class == expected:
            consecutive += 1
            if consecutive >= 2:
                return latest
        else:
            expected = latest.failure_class
            consecutive = 1
    if config.policy.failure_confirmation_attempts == 1:
        return latest
    return Diagnosis(latest.checked_at, False, "UNSTABLE_FAILURE", latest.checks)


def _copy_evidence(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(source, destination)
    return {
        "path": str(source),
        "artifact": str(destination),
        "sha256": sha256_file(destination),
        "size": destination.stat().st_size,
        "mode": stat.S_IMODE(source.stat().st_mode),
        "uid": source.stat().st_uid,
        "gid": source.stat().st_gid,
    }


def _quarantine_targets(manifest: dict[str, Any], quarantine: Path) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    for item in manifest["items"]:
        if item.get("missing"):
            continue
        target = Path(item["restore"])
        item_root = quarantine / "failed-state" / item["name"]
        record: dict[str, Any] = {
            "name": item["name"],
            "kind": item["kind"],
            "restore": str(target),
            "files": [],
        }
        if item["kind"] == "tree":
            if target.exists():
                if not target.is_dir() or target.is_symlink():
                    raise RuntimeError(f"unsafe recovery tree target: {target}")
                tree_archive = item_root / "tree.tar"
                tree_archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tarfile.open(tree_archive, "w", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                    for child in sorted(target.iterdir()):
                        archive.add(child, arcname=child.name, recursive=True)
                record["files"].append({
                    "path": str(target),
                    "artifact": str(tree_archive),
                    "sha256": sha256_file(tree_archive),
                    "size": tree_archive.stat().st_size,
                    "mode": stat.S_IMODE(target.stat().st_mode),
                    "uid": target.stat().st_uid,
                    "gid": target.stat().st_gid,
                })
            captured.append(record)
            continue
        if item["kind"] == "symlink":
            if target.is_symlink():
                link_target = os.readlink(target)
                record["files"].append({
                    "path": str(target),
                    "link_target": link_target,
                    "sha256": hashlib.sha256(link_target.encode()).hexdigest(),
                })
            elif target.exists():
                raise RuntimeError(f"symlink recovery target is not a symlink: {target}")
            captured.append(record)
            continue
        candidates = [(target, "main")]
        if item["kind"] == "sqlite":
            candidates.extend((Path(f"{target}{suffix}"), suffix[1:]) for suffix in ("-wal", "-shm"))
        for source, label in candidates:
            if not source.exists():
                continue
            if not source.is_file() or source.is_symlink():
                raise RuntimeError(f"unsafe recovery target: {source}")
            record["files"].append(_copy_evidence(source, item_root / label))
        captured.append(record)
    atomic_write(quarantine / "failed-state.json", canonical_json_bytes(captured), mode=0o600)
    return captured


def _apply_metadata(path: Path, metadata: dict[str, Any]) -> None:
    os.chmod(path, int(metadata["mode"]))
    try:
        os.chown(path, int(metadata["uid"]), int(metadata["gid"]))
    except PermissionError:
        current = path.stat()
        if current.st_uid != int(metadata["uid"]) or current.st_gid != int(metadata["gid"]):
            raise


def _restore_artifact(checkpoint: Path, item: dict[str, Any]) -> None:
    artifact = checkpoint / item["artifact"]
    target = Path(item["restore"])
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.lifeboat-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with artifact.open("rb") as source, os.fdopen(descriptor, "wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if sha256_file(temporary) != item["sha256"]:
            raise RuntimeError(f"staged restore hash mismatch: {item['name']}")
        _apply_metadata(temporary, item["metadata"])
        os.replace(temporary, target)
        fsync_directory(target.parent)
        if item["kind"] == "sqlite":
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{target}{suffix}")
                with contextlib.suppress(FileNotFoundError):
                    sidecar.unlink()
            fsync_directory(target.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _restore_tree(checkpoint: Path, item: dict[str, Any]) -> None:
    artifact = checkpoint / item["artifact"]
    target = Path(item["restore"])
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.lifeboat-stage-", dir=target.parent))
    displaced = target.parent / f".{target.name}.lifeboat-displaced-{uuid.uuid4().hex}"
    try:
        with tarfile.open(artifact, "r") as archive:
            archive.extractall(stage, filter="data")
        _apply_metadata(stage, item["metadata"])
        if target.exists():
            os.replace(target, displaced)
        try:
            os.replace(stage, target)
            fsync_directory(target.parent)
        except BaseException:
            if displaced.exists() and not target.exists():
                os.replace(displaced, target)
            raise
        if displaced.exists():
            shutil.rmtree(displaced)
            fsync_directory(target.parent)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _restore_symlink(item: dict[str, Any]) -> None:
    target = Path(item["restore"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.lifeboat-link-{uuid.uuid4().hex}"
    os.symlink(item["link_target"], temporary)
    try:
        os.replace(temporary, target)
        fsync_directory(target.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _write_receipt(config: Config, incident_id: str, receipt: dict[str, Any]) -> Path:
    path = config.store.root / "receipts" / f"{incident_id}.json"
    atomic_write(path, canonical_json_bytes(receipt), mode=0o600)
    return path


def _preflight_manifest(config: Config, checkpoint_id: str) -> tuple[Path, dict[str, Any]]:
    verify_checkpoint(config, checkpoint_id)
    checkpoint = config.store.root / "checkpoints" / checkpoint_id
    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    configured = {
        item.name: str(item.restore)
        for item in (*config.files, *config.databases, *config.trees, *config.symlinks)
    }
    database_specs = {item.name: item for item in config.databases}
    tree_roots = tuple(item.restore for item in config.trees)
    for item in manifest["items"]:
        if item.get("missing"):
            continue
        if configured.get(item["name"]) != item["restore"]:
            raise RuntimeError(f"restore target changed since checkpoint: {item['name']}")
        if item["kind"] == "sqlite":
            spec = database_specs[item["name"]]
            if spec.expected_user_version is not None \
                    and item["sqlite"]["user_version"] != spec.expected_user_version:
                raise RuntimeError(f"checkpoint database version is incompatible: {item['name']}")
            if spec.expected_schema_sha256 \
                    and item["sqlite"]["schema_sha256"] != spec.expected_schema_sha256:
                raise RuntimeError(f"checkpoint database schema is incompatible: {item['name']}")
        target_parent = Path(item["restore"]).parent
        if not target_parent.exists() or not target_parent.is_dir():
            covered_by_tree = any(
                target_parent == tree or tree in target_parent.parents for tree in tree_roots
            )
            if not covered_by_tree:
                raise RuntimeError(f"restore parent is unavailable: {target_parent}")
    return checkpoint, manifest


def recover_automatically(config: Config, *, fail_after_restores: int | None = None) -> dict[str, Any]:
    """Perform at most one policy-authorised rollback for a persistent failure.

    ``fail_after_restores`` exists solely for the disposable interrupted-restore
    acceptance test and is not exposed by the command line.
    """
    validate_store_mount(
        config.store.mountpoint, config.store.root, config.store.minimum_free_bytes,
        config.store.require_mountpoint, config.store.expected_mount_source,
        config.store.expected_filesystem,
    )
    ensure_store_layout(config.store.root)
    with exclusive_lock(config.store.root / "locks" / "controller.lock"):
        validate_store(
            config.store.root, config.store.mountpoint, config.store.minimum_free_bytes,
            config.store.require_mountpoint, config.store.expected_mount_source,
            config.store.expected_filesystem,
        )
        diagnosis = _confirm_failure(config)
        if diagnosis.healthy:
            return {"status": "healthy", "diagnosis": diagnosis.as_dict()}

        if diagnosis.failure_class == "PROCESS_CRASH":
            restart_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-restart-" + uuid.uuid4().hex[:8]
            restart_receipt: dict[str, Any] = {
                "schema": RECEIPT_SCHEMA,
                "incident_id": restart_id,
                "started_at": utc_now(),
                "trigger": "persistent process failure",
                "diagnosis": diagnosis.as_dict(),
                "commands": [],
                "files_quarantined": [],
                "files_restored": [],
            }
            try:
                journal = _run(
                    config.service.journal_command,
                    config.service.command_timeout_seconds,
                    required=False,
                )
                restart_receipt["commands"].append({"phase": "evidence-journal", **journal})
                started = _run(config.service.start_command, config.service.command_timeout_seconds)
                restart_receipt["commands"].append({"phase": "bounded-start", **started})
                after_restart = wait_until_healthy(config)
                restart_receipt["post_restart_health"] = after_restart.as_dict()
                restart_receipt["completed_at"] = utc_now()
                if after_restart.healthy:
                    restart_receipt["outcome"] = "restarted"
                    restart_path = _write_receipt(config, restart_id, restart_receipt)
                    return {**restart_receipt, "receipt_path": str(restart_path)}
                restart_receipt["outcome"] = "restart-failed"
                diagnosis = after_restart
            except BaseException as error:
                restart_receipt["outcome"] = "restart-failed"
                restart_receipt["error"] = f"{type(error).__name__}: {error}"
                restart_receipt["completed_at"] = utc_now()
            _write_receipt(config, restart_id, restart_receipt)

        eligible, reason, window = window_eligibility(config)
        if not eligible or window is None:
            return {
                "status": "operator-intervention-required",
                "reason": reason,
                "diagnosis": diagnosis.as_dict(),
            }
        if diagnosis.failure_class not in config.policy.automatic_failure_classes:
            return {
                "status": "operator-intervention-required",
                "reason": f"failure class is not authorised for rollback: {diagnosis.failure_class}",
                "diagnosis": diagnosis.as_dict(),
            }

        incident_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        checkpoint_id = window["checkpoint_id"]
        try:
            checkpoint, manifest = _preflight_manifest(config, checkpoint_id)
        except BaseException as error:
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "incident_id": incident_id,
                "started_at": utc_now(),
                "completed_at": utc_now(),
                "trigger": "persistent health failure during authorised change window",
                "diagnosis": diagnosis.as_dict(),
                "checkpoint_id": checkpoint_id,
                "outcome": "operator-intervention-required",
                "error": f"checkpoint rejected before service stop: {type(error).__name__}: {error}",
                "files_quarantined": [],
                "files_restored": [],
            }
            close_window(config, "checkpoint-rejected")
            receipt_path = _write_receipt(config, incident_id, receipt)
            return {**receipt, "receipt_path": str(receipt_path)}
        claimed = claim_rollback(config, incident_id)
        quarantine = config.store.root / "quarantine" / incident_id
        quarantine.mkdir(mode=0o700)
        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "incident_id": incident_id,
            "started_at": utc_now(),
            "trigger": "persistent health failure during authorised change window",
            "diagnosis": diagnosis.as_dict(),
            "application": manifest["application"],
            "checkpoint_id": checkpoint_id,
            "checkpoint_manifest_sha256": claimed["checkpoint_manifest_sha256"],
            "commands": [],
            "quarantine": str(quarantine),
            "files_quarantined": [],
            "files_restored": [],
            "outcome": "in-progress",
        }
        _write_receipt(config, incident_id, receipt)
        try:
            journal = _run(
                config.service.journal_command,
                config.service.command_timeout_seconds,
                required=False,
            )
            receipt["commands"].append({"phase": "evidence-journal", **journal})
            atomic_write(quarantine / "diagnosis.json", canonical_json_bytes(diagnosis.as_dict()))
            atomic_write(quarantine / "journal.json", canonical_json_bytes(journal))

            stopped = _run(config.service.stop_command, config.service.command_timeout_seconds)
            receipt["commands"].append({"phase": "stop", **stopped})
            receipt["files_quarantined"] = _quarantine_targets(manifest, quarantine)

            restored_count = 0
            ordered_items = sorted(
                manifest["items"],
                key=lambda item: {"tree": 0, "file": 1, "sqlite": 2, "symlink": 3}[item["kind"]],
            )
            for item in ordered_items:
                if item.get("missing"):
                    continue
                if item["kind"] == "tree":
                    _restore_tree(checkpoint, item)
                elif item["kind"] == "symlink":
                    _restore_symlink(item)
                else:
                    _restore_artifact(checkpoint, item)
                receipt["files_restored"].append({
                    "name": item["name"],
                    "restore": item["restore"],
                    "sha256": item["sha256"],
                })
                restored_count += 1
                _write_receipt(config, incident_id, receipt)
                if fail_after_restores is not None and restored_count >= fail_after_restores:
                    raise RuntimeError("deliberate interrupted-restore failpoint")

            started = _run(config.service.start_command, config.service.command_timeout_seconds)
            receipt["commands"].append({"phase": "start", **started})
            final_health = wait_until_healthy(config)
            receipt["post_recovery_health"] = final_health.as_dict()
            if not final_health.healthy:
                raise RuntimeError(f"post-recovery health failed: {final_health.failure_class}")
            receipt["outcome"] = "recovered"
            receipt["completed_at"] = utc_now()
            close_window(config, "recovered")
        except BaseException as error:
            receipt["outcome"] = "operator-intervention-required"
            receipt["error"] = f"{type(error).__name__}: {error}"
            receipt["completed_at"] = utc_now()
            # Deliberately do not improvise a second restore or consume another
            # checkpoint. Failed state and partially restored targets remain
            # evidenced; the claimed attempt prevents a loop.
        receipt_path = _write_receipt(config, incident_id, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}


def _restore_evidence_file(evidence: dict[str, Any]) -> None:
    source = Path(evidence["artifact"])
    target = Path(evidence["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.lifeboat-undo-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        if sha256_file(temporary) != evidence["sha256"]:
            raise RuntimeError(f"quarantine artifact hash mismatch: {source}")
        _apply_metadata(temporary, evidence)
        os.replace(temporary, target)
        fsync_directory(target.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _restore_evidence_tree(record: dict[str, Any]) -> None:
    evidence = record["files"][0]
    archive_path = Path(evidence["artifact"])
    if sha256_file(archive_path) != evidence["sha256"]:
        raise RuntimeError(f"quarantine tree hash mismatch: {record['name']}")
    target = Path(record["restore"])
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.lifeboat-undo-stage-", dir=target.parent))
    displaced = target.parent / f".{target.name}.lifeboat-undo-displaced-{uuid.uuid4().hex}"
    try:
        with tarfile.open(archive_path, "r") as archive:
            archive.extractall(stage, filter="data")
        _apply_metadata(stage, evidence)
        if target.exists():
            os.replace(target, displaced)
        try:
            os.replace(stage, target)
        except BaseException:
            if displaced.exists() and not target.exists():
                os.replace(displaced, target)
            raise
        if displaced.exists():
            shutil.rmtree(displaced)
        fsync_directory(target.parent)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def undo_recovery(config: Config, incident_id: str) -> dict[str, Any]:
    """Explicitly restore the quarantined pre-recovery state for one incident."""
    if not incident_id or "/" in incident_id or incident_id.startswith("."):
        raise ValueError("invalid incident id")
    validate_store_mount(
        config.store.mountpoint, config.store.root, config.store.minimum_free_bytes,
        config.store.require_mountpoint, config.store.expected_mount_source,
        config.store.expected_filesystem,
    )
    with exclusive_lock(config.store.root / "locks" / "controller.lock"):
        original_receipt_path = config.store.root / "receipts" / f"{incident_id}.json"
        original_receipt = json.loads(original_receipt_path.read_text(encoding="utf-8"))
        quarantine = (config.store.root / "quarantine" / incident_id).resolve()
        if config.store.root.resolve() not in quarantine.parents or not quarantine.is_dir():
            raise RuntimeError("incident quarantine is unavailable")
        records = original_receipt.get("files_quarantined", [])
        if not records:
            raise RuntimeError("incident has no quarantined failed state")
        undo_id = f"undo-{incident_id}-{uuid.uuid4().hex[:8]}"
        receipt: dict[str, Any] = {
            "schema": RECEIPT_SCHEMA,
            "incident_id": undo_id,
            "undoes_incident_id": incident_id,
            "started_at": utc_now(),
            "commands": [],
            "outcome": "in-progress",
        }
        stopped = _run(config.service.stop_command, config.service.command_timeout_seconds)
        receipt["commands"].append({"phase": "stop", **stopped})
        try:
            ordered = sorted(records, key=lambda record: 0 if record["kind"] == "tree" else 1)
            for record in ordered:
                if record["kind"] == "tree":
                    if record["files"]:
                        _restore_evidence_tree(record)
                elif record["kind"] == "symlink":
                    target = Path(record["restore"])
                    if record["files"]:
                        evidence = record["files"][0]
                        temporary = target.parent / f".{target.name}.lifeboat-undo-link-{uuid.uuid4().hex}"
                        os.symlink(evidence["link_target"], temporary)
                        os.replace(temporary, target)
                    else:
                        with contextlib.suppress(FileNotFoundError):
                            target.unlink()
                else:
                    evidence_paths = {entry["path"] for entry in record["files"]}
                    if record["kind"] == "sqlite":
                        target = Path(record["restore"])
                        for suffix in ("-wal", "-shm"):
                            sidecar = Path(f"{target}{suffix}")
                            if str(sidecar) not in evidence_paths:
                                with contextlib.suppress(FileNotFoundError):
                                    sidecar.unlink()
                    for evidence in record["files"]:
                        _restore_evidence_file(evidence)
            started = _run(config.service.start_command, config.service.command_timeout_seconds)
            receipt["commands"].append({"phase": "start", **started})
            receipt["post_undo_health"] = diagnose(config).as_dict()
            receipt["outcome"] = "undone"
            receipt["completed_at"] = utc_now()
        except BaseException as error:
            receipt["outcome"] = "operator-intervention-required"
            receipt["error"] = f"{type(error).__name__}: {error}"
            receipt["completed_at"] = utc_now()
        receipt_path = _write_receipt(config, undo_id, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
