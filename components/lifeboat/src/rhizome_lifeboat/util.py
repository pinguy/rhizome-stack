from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary_path.unlink()
        raise


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_store_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    for name in ("checkpoints", "quarantine", "receipts", "manifests", "state", "locks"):
        directory = root / name
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def mount_info(path: Path) -> dict[str, str] | None:
    resolved = path.resolve()
    best: tuple[int, dict[str, str]] | None = None
    with Path("/proc/self/mountinfo").open("r", encoding="utf-8") as handle:
        for line in handle:
            left, right = line.rstrip("\n").split(" - ", 1)
            fields = left.split()
            mount_point = Path(fields[4].replace("\\040", " ")).resolve()
            try:
                resolved.relative_to(mount_point)
            except ValueError:
                continue
            right_fields = right.split()
            candidate = {
                "mount_point": str(mount_point),
                "filesystem": right_fields[0],
                "source": right_fields[1],
                "options": fields[5],
            }
            length = len(str(mount_point))
            if best is None or length > best[0]:
                best = (length, candidate)
    return best[1] if best else None


def validate_store_mount(mountpoint: Path, root: Path, minimum_free_bytes: int,
                         require_mountpoint: bool, expected_source: str | None,
                         expected_filesystem: str | None) -> dict[str, Any]:
    """Validate the backing volume before any store directory is created.

    Checking ``root`` after creating it is unsafe: if the backup mount is absent, a
    directory with the same name can exist on the root filesystem and silently
    receive recovery data. The configured mountpoint is therefore checked
    first and must own the filesystem containing the future store root.
    """
    if not mountpoint.exists() or not mountpoint.is_dir():
        raise RuntimeError(f"store mountpoint is unavailable: {mountpoint}")
    mount_info_for_point = mount_info(mountpoint)
    if mount_info_for_point is None:
        raise RuntimeError(f"cannot identify store mountpoint filesystem: {mountpoint}")
    actual_mountpoint = Path(mount_info_for_point["mount_point"])
    if require_mountpoint and actual_mountpoint.resolve() != mountpoint.resolve():
        raise RuntimeError(f"configured store mountpoint is not mounted: {mountpoint}")
    try:
        root.resolve(strict=False).relative_to(mountpoint.resolve())
    except ValueError as error:
        raise RuntimeError(f"store root is outside configured mountpoint: {root}") from error
    if expected_filesystem and mount_info_for_point["filesystem"] != expected_filesystem:
        raise RuntimeError(
            f"store filesystem mismatch: expected {expected_filesystem}, "
            f"got {mount_info_for_point['filesystem']}"
        )
    if expected_source:
        actual = Path(mount_info_for_point["source"]).resolve()
        expected = Path(expected_source).resolve()
        if actual != expected:
            raise RuntimeError(f"store source mismatch: expected {expected}, got {actual}")
    usage = shutil.disk_usage(mountpoint)
    if usage.free < minimum_free_bytes:
        raise RuntimeError(
            f"store has insufficient free space: {usage.free} < {minimum_free_bytes}"
        )
    return {
        **mount_info_for_point,
        "configured_mountpoint": str(mountpoint),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def validate_store(root: Path, mountpoint: Path, minimum_free_bytes: int,
                   require_mountpoint: bool, expected_source: str | None,
                   expected_filesystem: str | None) -> dict[str, Any]:
    info = validate_store_mount(
        mountpoint, root, minimum_free_bytes, require_mountpoint,
        expected_source, expected_filesystem,
    )
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"store root is unavailable: {root}")
    root_info = mount_info(root)
    if root_info is None:
        raise RuntimeError(f"cannot identify filesystem for store: {root}")
    # systemd's ReadWritePaths creates a bind mount at the narrowly writable
    # store root. That legitimately changes the namespace-visible mount point
    # while retaining the same backing source and filesystem. Requiring an
    # identical mount-point string breaks both scheduled checkpoints and the
    # recovery unit; source/filesystem identity preserves the safety property
    # without widening either unit's write boundary to the whole volume.
    if root_info["source"] != info["source"] or root_info["filesystem"] != info["filesystem"]:
        raise RuntimeError(f"store root is not on configured store volume: {root}")
    return info
