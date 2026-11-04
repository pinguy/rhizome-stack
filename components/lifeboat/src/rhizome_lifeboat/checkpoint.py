from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
import contextlib
import fnmatch
import tarfile
import posixpath
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import Config, DatabaseSpec, FileSpec, SymlinkSpec, TreeSpec
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


MANIFEST_SCHEMA = "rhizome-lifeboat-checkpoint-v1"
MAX_CHECKPOINT_WORKERS = 8
GNU_TAR = Path("/usr/bin/tar")


def _worker_count(task_count: int) -> int:
    return max(1, min(task_count, os.cpu_count() or 1, MAX_CHECKPOINT_WORKERS))


def _schema_details(connection: sqlite3.Connection) -> dict[str, Any]:
    quick = connection.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        raise RuntimeError(f"SQLite integrity failure: {quick}")
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
    rows = connection.execute(
        "SELECT type,name,coalesce(sql,'') FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    material = "\n".join("\t".join(str(value) for value in row) for row in rows).encode()
    return {
        "quick_check": quick,
        "user_version": user_version,
        "application_id": application_id,
        "schema_version": schema_version,
        "schema_sha256": hashlib.sha256(material).hexdigest(),
        "table_count": sum(1 for row in rows if row[0] == "table"),
    }


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path))}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def sqlite_details(path: Path) -> dict[str, Any]:
    with contextlib.closing(_read_only_connection(path)) as connection:
        return _schema_details(connection)


def _safe_name(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_." else "-" for character in value)
    if not safe or safe in {".", ".."}:
        raise ValueError(f"unsafe item name: {value!r}")
    return safe


def _metadata(path: Path) -> dict[str, Any]:
    info = path.stat()
    return {
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mtime_ns": info.st_mtime_ns,
        "size": info.st_size,
    }


def _copy_file(spec: FileSpec, data_root: Path) -> dict[str, Any]:
    if not spec.source.exists():
        if spec.required:
            raise FileNotFoundError(spec.source)
        return {"name": spec.name, "kind": "file", "required": False, "missing": True}
    if not spec.source.is_file() or spec.source.is_symlink():
        raise RuntimeError(f"checkpoint file is not a regular file: {spec.source}")
    destination = data_root / "files" / _safe_name(spec.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(spec.source, destination)
    return {
        "name": spec.name,
        "kind": "file",
        "source": str(spec.source),
        "restore": str(spec.restore),
        "artifact": str(destination.relative_to(data_root.parent)),
        "sha256": sha256_file(destination),
        "metadata": _metadata(spec.source),
    }


def _copy_database(spec: DatabaseSpec, data_root: Path) -> dict[str, Any]:
    if not spec.source.exists():
        if spec.required:
            raise FileNotFoundError(spec.source)
        return {"name": spec.name, "kind": "sqlite", "required": False, "missing": True}

    destination = data_root / "databases" / f"{_safe_name(spec.name)}.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep one source handle from admission check through backup. Reopening a
    # small live state database between those phases creates a TOCTOU race with
    # applications that atomically replace the file.
    with contextlib.closing(_read_only_connection(spec.source)) as source:
        source_details = _schema_details(source)
        if spec.expected_user_version is not None and source_details["user_version"] != spec.expected_user_version:
            raise RuntimeError(
                f"{spec.name} user_version mismatch: {source_details['user_version']} != {spec.expected_user_version}"
            )
        if spec.expected_schema_sha256 and source_details["schema_sha256"] != spec.expected_schema_sha256:
            raise RuntimeError(f"{spec.name} schema fingerprint mismatch")

        with contextlib.closing(sqlite3.connect(destination)) as target:
            # Copy the remaining database in one backup step. Chunked backups
            # can restart indefinitely when a hot source changes between
            # steps; one step cannot be starved by continuous writers.
            source.backup(target, pages=-1)
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            # Recovery artefacts must be self-contained. The online backup can
            # inherit WAL mode from the source even though its pages are
            # already a consistent snapshot, so convert only the copied
            # database to DELETE journalling before it is hashed and promoted.
            journal_mode = target.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(journal_mode).lower() != "delete":
                raise RuntimeError(f"could not make {spec.name} snapshot self-contained")
            target.commit()
    os.chmod(destination, stat.S_IMODE(spec.source.stat().st_mode))
    snapshot_details = sqlite_details(destination)
    if source_details["user_version"] != snapshot_details["user_version"]:
        raise RuntimeError(f"{spec.name} backup user_version changed")
    if source_details["schema_sha256"] != snapshot_details["schema_sha256"]:
        raise RuntimeError(f"{spec.name} backup schema changed")
    return {
        "name": spec.name,
        "kind": "sqlite",
        "source": str(spec.source),
        "restore": str(spec.restore),
        "artifact": str(destination.relative_to(data_root.parent)),
        "sha256": sha256_file(destination),
        "metadata": _metadata(spec.source),
        "sqlite": snapshot_details,
    }


def _excluded(relative: Path, patterns: tuple[str, ...]) -> bool:
    value = relative.as_posix()
    return any(fnmatch.fnmatchcase(value, pattern) or relative.match(pattern) for pattern in patterns)


def _copy_tree(spec: TreeSpec, data_root: Path) -> dict[str, Any]:
    if not spec.source.exists():
        if spec.required:
            raise FileNotFoundError(spec.source)
        return {"name": spec.name, "kind": "tree", "required": False, "missing": True}
    if not spec.source.is_dir() or spec.source.is_symlink():
        raise RuntimeError(f"checkpoint tree is not a real directory: {spec.source}")
    destination = data_root / "trees" / f"{_safe_name(spec.name)}.tar"
    destination.parent.mkdir(parents=True, exist_ok=True)
    relative_members: list[str] = []
    for path in sorted(spec.source.rglob("*")):
        relative = path.relative_to(spec.source)
        if _excluded(relative, spec.exclude):
            continue
        if any(_excluded(parent, spec.exclude) for parent in relative.parents if str(parent) != "."):
            continue
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise RuntimeError(f"unsupported tree entry: {path}")
        lowered = relative.name.lower()
        if stat.S_ISREG(info.st_mode) and (".sqlite" in lowered or lowered.endswith(("-wal", "-shm"))):
            raise RuntimeError(
                f"live SQLite-like file must be separately configured or excluded: {path}"
            )
        relative_members.append(relative.as_posix())

    if not GNU_TAR.is_file() or not os.access(GNU_TAR, os.X_OK):
        raise RuntimeError(f"required GNU tar executable is unavailable: {GNU_TAR}")
    file_list = b"\0".join(os.fsencode(member) for member in relative_members)
    if file_list:
        file_list += b"\0"
    completed = subprocess.run(
        [
            str(GNU_TAR),
            "--create",
            f"--file={destination}",
            "--format=pax",
            "--no-recursion",
            "--null",
            "--verbatim-files-from",
            "--files-from=-",
        ],
        cwd=spec.source,
        input=file_list,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"GNU tar failed for {spec.name}: {detail}")
    members = len(relative_members)
    return {
        "name": spec.name,
        "kind": "tree",
        "source": str(spec.source),
        "restore": str(spec.restore),
        "artifact": str(destination.relative_to(data_root.parent)),
        "sha256": sha256_file(destination),
        "metadata": _metadata(spec.source),
        "tree": {"members": members, "exclude": list(spec.exclude)},
    }


def _validate_tree_archive(path: Path) -> int:
    count = 0
    with tarfile.open(path, "r") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(f"unsafe tree archive member: {member.name}")
            if member.isdev() or member.isfifo():
                raise RuntimeError(f"unsupported tree archive member: {member.name}")
            if member.issym() or member.islnk():
                link = Path(member.linkname)
                if member.issym():
                    resolved_link = posixpath.normpath(
                        posixpath.join(posixpath.dirname(member.name), member.linkname)
                    )
                else:
                    resolved_link = posixpath.normpath(member.linkname)
                if link.is_absolute() or resolved_link == ".." or resolved_link.startswith("../"):
                    raise RuntimeError(f"unsafe tree archive link: {member.name}")
            count += 1
    return count


def _copy_symlink(spec: SymlinkSpec) -> dict[str, Any]:
    if not spec.source.is_symlink():
        if not spec.source.exists() and not spec.required:
            return {"name": spec.name, "kind": "symlink", "required": False, "missing": True}
        raise RuntimeError(f"checkpoint symlink is missing or not a symlink: {spec.source}")
    target = os.readlink(spec.source)
    return {
        "name": spec.name,
        "kind": "symlink",
        "source": str(spec.source),
        "restore": str(spec.restore),
        "link_target": target,
        "sha256": hashlib.sha256(target.encode()).hexdigest(),
        "metadata": _metadata(spec.source),
    }


def _copy_checkpoint_item(task: tuple[str, object, Path]) -> dict[str, Any]:
    kind, spec, data_root = task
    try:
        if kind == "file":
            return _copy_file(spec, data_root)  # type: ignore[arg-type]
        if kind == "sqlite":
            return _copy_database(spec, data_root)  # type: ignore[arg-type]
        if kind == "tree":
            return _copy_tree(spec, data_root)  # type: ignore[arg-type]
        if kind == "symlink":
            return _copy_symlink(spec)  # type: ignore[arg-type]
        raise ValueError(f"unknown checkpoint item kind: {kind}")
    except Exception as error:
        item_name = getattr(spec, "name", "unknown")
        raise RuntimeError(f"checkpoint {kind} item {item_name} failed: {error}") from error


def create_checkpoint(config: Config, reason: str, checkpoint_kind: str = "manual") -> dict[str, Any]:
    # Verify the separate backup volume before creating anything beneath the
    # store root. This prevents an absent backup mount from filling /.
    validate_store_mount(
        config.store.mountpoint,
        config.store.root,
        config.store.minimum_free_bytes,
        config.store.require_mountpoint,
        config.store.expected_mount_source,
        config.store.expected_filesystem,
    )
    ensure_store_layout(config.store.root)
    with exclusive_lock(config.store.root / "locks" / "controller.lock"):
        store_info = validate_store(
            config.store.root,
            config.store.mountpoint,
            config.store.minimum_free_bytes,
            config.store.require_mountpoint,
            config.store.expected_mount_source,
            config.store.expected_filesystem,
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        checkpoint_id = f"{stamp}-{uuid.uuid4().hex[:10]}"
        partial = config.store.root / "checkpoints" / f".{checkpoint_id}.partial"
        final = config.store.root / "checkpoints" / checkpoint_id
        partial.mkdir(mode=0o700)
        data_root = partial / "data"
        data_root.mkdir(mode=0o700)
        try:
            tasks = (
                [("file", spec, data_root) for spec in config.files]
                + [("sqlite", spec, data_root) for spec in config.databases]
                + [("tree", spec, data_root) for spec in config.trees]
                + [("symlink", spec, data_root) for spec in config.symlinks]
            )
            with ProcessPoolExecutor(max_workers=_worker_count(len(tasks))) as executor:
                # map preserves configured item order while independent file,
                # database and tree snapshots use the host's available CPUs.
                items = list(executor.map(_copy_checkpoint_item, tasks))
            manifest = {
                "schema": MANIFEST_SCHEMA,
                "checkpoint_id": checkpoint_id,
                "created_at": utc_now(),
                "kind": checkpoint_kind,
                "reason": reason,
                "application": {
                    "name": config.application.name,
                    "version": config.application.version,
                    "revision": config.application.revision,
                },
                "store": store_info,
                "items": items,
                "verified": True,
            }
            manifest_bytes = canonical_json_bytes(manifest)
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
            atomic_write(partial / "manifest.json", manifest_bytes)
            atomic_write(partial / "manifest.sha256", f"{manifest_sha}  manifest.json\n".encode())
            atomic_write(partial / "VERIFIED", f"{manifest_sha}\n".encode())
            fsync_directory(partial)
            os.replace(partial, final)
            fsync_directory(final.parent)
            atomic_write(
                config.store.root / "manifests" / f"{checkpoint_id}.json",
                manifest_bytes,
            )
            verified = verify_checkpoint(config, checkpoint_id)
            if config.retention.enabled:
                # Retention shares the controller lock and can only run after
                # this new point has passed full compatibility verification.
                from .retention import prune_checkpoints

                verified["retention"] = prune_checkpoints(
                    config,
                    dry_run=False,
                    required_new_checkpoint_id=checkpoint_id,
                    assume_locked=True,
                )
            return verified
        except BaseException:
            # A partial directory is intentionally retained as evidence and is never trusted.
            raise


def _load_manifest(checkpoint: Path) -> tuple[dict[str, Any], str]:
    manifest_path = checkpoint / "manifest.json"
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    sidecar = (checkpoint / "manifest.sha256").read_text(encoding="utf-8").split()[0]
    marker = (checkpoint / "VERIFIED").read_text(encoding="utf-8").strip()
    if digest != sidecar or digest != marker:
        raise RuntimeError("checkpoint manifest digest mismatch")
    manifest = json.loads(raw)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise RuntimeError("unsupported checkpoint manifest schema")
    if not manifest.get("verified"):
        raise RuntimeError("checkpoint is not marked verified")
    return manifest, digest


def _verify_checkpoint_item(task: tuple[Path, dict[str, Any]]) -> int:
    checkpoint, item = task
    if item.get("missing"):
        return 0
    if item["kind"] == "symlink":
        if hashlib.sha256(item["link_target"].encode()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"checkpoint symlink hash mismatch: {item['name']}")
        return 1
    artifact = checkpoint / item["artifact"]
    if not artifact.is_file():
        raise RuntimeError(f"missing checkpoint artifact: {item['name']}")
    if sha256_file(artifact) != item["sha256"]:
        raise RuntimeError(f"checkpoint artifact hash mismatch: {item['name']}")
    if item["kind"] == "sqlite":
        details = sqlite_details(artifact)
        if details["quick_check"] != "ok":
            raise RuntimeError(f"checkpoint database integrity failure: {item['name']}")
        if details["user_version"] != item["sqlite"]["user_version"]:
            raise RuntimeError(f"checkpoint database version mismatch: {item['name']}")
        if details["schema_sha256"] != item["sqlite"]["schema_sha256"]:
            raise RuntimeError(f"checkpoint database schema mismatch: {item['name']}")
    elif item["kind"] == "tree":
        members = _validate_tree_archive(artifact)
        if members != item["tree"]["members"]:
            raise RuntimeError(f"checkpoint tree member count mismatch: {item['name']}")
    return 1


def verify_checkpoint(config: Config, checkpoint_id: str) -> dict[str, Any]:
    if checkpoint_id.startswith(".") or "/" in checkpoint_id:
        raise ValueError("invalid checkpoint id")
    checkpoint = config.store.root / "checkpoints" / checkpoint_id
    if not checkpoint.is_dir():
        raise FileNotFoundError(checkpoint)
    manifest, manifest_digest = _load_manifest(checkpoint)
    if manifest["application"] != {
        "name": config.application.name,
        "version": config.application.version,
        "revision": config.application.revision,
    }:
        raise RuntimeError("checkpoint application version/revision mismatch")
    tasks = [(checkpoint, item) for item in manifest["items"]]
    with ProcessPoolExecutor(max_workers=_worker_count(len(tasks))) as executor:
        checked = sum(executor.map(_verify_checkpoint_item, tasks))
    return {
        "checkpoint_id": checkpoint_id,
        "manifest_sha256": manifest_digest,
        "items_verified": checked,
        "application": manifest["application"],
        "created_at": manifest["created_at"],
        "status": "verified",
    }


def list_checkpoints(config: Config) -> list[dict[str, Any]]:
    root = config.store.root / "checkpoints"
    if not root.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            result = verify_checkpoint(config, path.name)
        except Exception as error:  # Listing must expose bad candidates, not hide them.
            result = {"checkpoint_id": path.name, "status": "invalid", "error": str(error)}
        results.append(result)
    return results
