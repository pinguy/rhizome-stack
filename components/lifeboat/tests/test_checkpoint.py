from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import contextlib
import tarfile
from pathlib import Path
from unittest.mock import patch

from rhizome_lifeboat.checkpoint import (
    _copy_tree,
    _validate_tree_archive,
    _worker_count,
    create_checkpoint,
    list_checkpoints,
    verify_checkpoint,
)
from rhizome_lifeboat.config import TreeSpec, load_config
from rhizome_lifeboat.util import validate_store


class CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.live = self.root / "live"
        self.store = self.root / "store"
        self.live.mkdir()
        self.store.mkdir()

        self.config_file = self.live / "openclaw.json"
        self.config_file.write_text('{"gateway":{"port":18789}}\n', encoding="utf-8")

        self.database = self.live / "state.sqlite"
        self.writer = sqlite3.connect(self.database)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("PRAGMA user_version=7")
        self.writer.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        self.writer.execute("INSERT INTO events(value) VALUES ('baseline')")
        self.writer.commit()

        self.config_path = self.root / "lifeboat.toml"
        self.config_path.write_text(
            f'''[store]
root = "{self.store}"
mountpoint = "{self.root}"
minimum_free_bytes = 0

[application]
name = "OpenClaw-test"
version = "1.0-test"
revision = "fixture"

[[files]]
name = "gateway-config"
source = "{self.config_file}"
restore = "{self.config_file}"

[[databases]]
name = "state"
source = "{self.database}"
restore = "{self.database}"
expected_user_version = 7
''',
            encoding="utf-8",
        )
        self.config = load_config(self.config_path)

    def tearDown(self) -> None:
        self.writer.close()
        self.temporary.cleanup()

    def test_parallel_worker_cap_uses_eight_of_twenty_logical_cpus(self) -> None:
        with patch("rhizome_lifeboat.checkpoint.os.cpu_count", return_value=20):
            self.assertEqual(_worker_count(46), 8)
            self.assertEqual(_worker_count(3), 3)

    def test_gnu_tar_tree_snapshot_uses_only_validated_members(self) -> None:
        tree = self.live / "plugin-tree"
        excluded = tree / "cache" / "nested"
        excluded.mkdir(parents=True)
        (tree / "runtime.js").write_text("known-good\n", encoding="utf-8")
        (tree / "-leading-dash").write_text("safe name\n", encoding="utf-8")
        (excluded / "ignored.js").write_text("excluded\n", encoding="utf-8")
        (tree / "runtime-link").symlink_to("runtime.js")
        data_root = self.root / "tree-checkpoint" / "data"
        spec = TreeSpec(
            name="plugins",
            source=tree,
            restore=tree,
            exclude=("cache",),
        )

        item = _copy_tree(spec, data_root)
        archive = data_root.parent / item["artifact"]
        self.assertEqual(_validate_tree_archive(archive), item["tree"]["members"])
        with tarfile.open(archive, "r:") as handle:
            names = [member.name for member in handle.getmembers()]
        self.assertEqual(names, ["-leading-dash", "runtime-link", "runtime.js"])
        self.assertNotIn("cache", names)

    def test_online_wal_backup_is_complete_and_independent(self) -> None:
        self.writer.execute("INSERT INTO events(value) VALUES ('in-wal')")
        self.writer.commit()
        self.assertTrue(Path(f"{self.database}-wal").exists())

        result = create_checkpoint(self.config, "unit-test", "pre-change")
        checkpoint = self.store / "checkpoints" / result["checkpoint_id"]
        manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
        database_item = next(item for item in manifest["items"] if item["kind"] == "sqlite")
        snapshot = checkpoint / database_item["artifact"]

        with contextlib.closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as connection:
            values = [row[0] for row in connection.execute("SELECT value FROM events ORDER BY id")]
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(values, ["baseline", "in-wal"])
        self.assertEqual(quick, "ok")
        self.assertEqual(user_version, 7)
        self.assertFalse(Path(f"{snapshot}-wal").exists())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["items_verified"], 2)

    def test_corrupted_candidate_is_rejected(self) -> None:
        result = create_checkpoint(self.config, "corruption-test")
        checkpoint = self.store / "checkpoints" / result["checkpoint_id"]
        manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
        database_item = next(item for item in manifest["items"] if item["kind"] == "sqlite")
        artifact = checkpoint / database_item["artifact"]
        with artifact.open("r+b") as handle:
            handle.seek(128)
            handle.write(b"deliberate-corruption")

        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            verify_checkpoint(self.config, result["checkpoint_id"])
        listing = list_checkpoints(self.config)
        self.assertEqual(listing[0]["status"], "invalid")

    def test_partial_checkpoint_is_never_listed(self) -> None:
        partial = self.store / "checkpoints" / ".interrupted.partial"
        partial.mkdir(parents=True)
        (partial / "untrusted").write_text("partial", encoding="utf-8")
        self.assertEqual(list_checkpoints(self.config), [])

    def test_wrong_live_schema_version_is_rejected_before_promotion(self) -> None:
        self.writer.execute("PRAGMA user_version=8")
        self.writer.commit()
        with self.assertRaisesRegex(RuntimeError, "user_version mismatch"):
            create_checkpoint(self.config, "wrong-schema")
        promoted = [path for path in (self.store / "checkpoints").iterdir() if not path.name.startswith(".")]
        self.assertEqual(promoted, [])
        partials = [path for path in (self.store / "checkpoints").iterdir() if path.name.startswith(".")]
        self.assertEqual(len(partials), 1)

    def test_missing_mountpoint_refuses_before_creating_store(self) -> None:
        missing_mount = self.root / "missing-volume"
        unsafe_store = missing_mount / "rhizome-lifeboat"
        config_path = self.root / "missing-mount.toml"
        config_path.write_text(
            self.config_path.read_text(encoding="utf-8")
            .replace(f'root = "{self.store}"', f'root = "{unsafe_store}"')
            .replace(f'mountpoint = "{self.root}"', f'mountpoint = "{missing_mount}"'),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "mountpoint is unavailable"):
            create_checkpoint(load_config(config_path), "missing-mount")
        self.assertFalse(missing_mount.exists())

    def test_narrow_systemd_bind_mount_keeps_store_volume_identity(self) -> None:
        volume = {
            "mount_point": str(self.root),
            "filesystem": "ext4",
            "source": "/dev/test-volume",
            "options": "rw",
        }
        bind = {**volume, "mount_point": str(self.store)}
        with patch(
            "rhizome_lifeboat.util.mount_info",
            side_effect=lambda path: volume if path == self.root else bind,
        ):
            result = validate_store(self.store, self.root, 0, False, None, None)
        self.assertEqual(result["source"], "/dev/test-volume")

    def test_store_bind_mount_on_different_source_is_rejected(self) -> None:
        volume = {
            "mount_point": str(self.root),
            "filesystem": "ext4",
            "source": "/dev/test-volume",
            "options": "rw",
        }
        wrong_bind = {
            **volume,
            "mount_point": str(self.store),
            "source": "/dev/wrong-volume",
        }
        with patch(
            "rhizome_lifeboat.util.mount_info",
            side_effect=lambda path: volume if path == self.root else wrong_bind,
        ):
            with self.assertRaisesRegex(RuntimeError, "not on configured store volume"):
                validate_store(self.store, self.root, 0, False, None, None)


if __name__ == "__main__":
    unittest.main()
