from __future__ import annotations

import dataclasses
import json
import multiprocessing
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rhizome_lifeboat.config import RetentionConfig, load_config
from rhizome_lifeboat.retention import (
    _active_references,
    inventory_checkpoints,
    prune_checkpoints,
    retention_plan,
    select_retention,
)
from rhizome_lifeboat.util import exclusive_lock


def _record(number: int, stamp: str, status: str = "verified") -> dict[str, object]:
    return {
        "checkpoint_id": f"20260101T000000Z-{number:010x}",
        "created_at": stamp,
        "manifest_sha256": f"sha-{number}",
        "status": status,
        "size_bytes": number * 1000,
    }


def _hold_lock(path: str, ready: multiprocessing.synchronize.Event,
               release: multiprocessing.synchronize.Event) -> None:
    with exclusive_lock(Path(path)):
        ready.set()
        release.wait(5)


class RetentionSelectorTests(unittest.TestCase):
    def test_fewer_than_six_bounds_redundant_same_day_but_keeps_fallback(self) -> None:
        records = [
            _record(3, "2026-11-04T14:00:00+00:00"),
            _record(2, "2026-11-04T09:00:00+00:00"),
            _record(1, "2026-11-04T04:00:00+00:00"),
        ]
        result = select_retention(records)
        self.assertEqual(
            [item["checkpoint_id"] for item in result["retained"]],
            [records[0]["checkpoint_id"], records[2]["checkpoint_id"]],
        )
        self.assertEqual(
            [item["checkpoint_id"] for item in result["delete"]],
            [records[1]["checkpoint_id"]],
        )

    def test_exactly_six_calendar_slots_are_distinct_and_all_retained(self) -> None:
        records = [
            _record(6, "2026-11-10T10:00:00+00:00"),
            _record(5, "2026-11-09T10:00:00+00:00"),
            _record(4, "2026-11-08T10:00:00+00:00"),
            _record(3, "2026-10-30T10:00:00+00:00"),
            _record(2, "2026-10-20T10:00:00+00:00"),
            _record(1, "2026-09-15T10:00:00+00:00"),
        ]
        result = select_retention(records)
        self.assertEqual(len(result["retained"]), 6)
        self.assertEqual(result["delete"], [])
        self.assertEqual(len({item["checkpoint_id"] for item in result["retained"]}), 6)

    def test_more_than_six_prunes_redundant_points(self) -> None:
        records = [
            _record(8, "2026-11-10T12:00:00+00:00"),
            _record(7, "2026-11-10T08:00:00+00:00"),
            _record(6, "2026-11-09T10:00:00+00:00"),
            _record(5, "2026-11-08T10:00:00+00:00"),
            _record(4, "2026-10-30T10:00:00+00:00"),
            _record(3, "2026-10-20T10:00:00+00:00"),
            _record(2, "2026-09-15T10:00:00+00:00"),
            _record(1, "2026-08-15T10:00:00+00:00"),
        ]
        result = select_retention(records)
        self.assertEqual(len(result["retained"]), 6)
        self.assertEqual(
            {item["checkpoint_id"] for item in result["delete"]},
            {records[1]["checkpoint_id"], records[-1]["checkpoint_id"]},
        )

    def test_missing_days_and_weeks_do_not_keep_every_history_point(self) -> None:
        records = [
            _record(5, "2026-11-10T12:00:00+00:00"),
            _record(4, "2026-11-10T08:00:00+00:00"),
            _record(3, "2026-11-08T10:00:00+00:00"),
            _record(2, "2026-11-01T10:00:00+00:00"),
            _record(1, "2026-11-01T08:00:00+00:00"),
        ]
        result = select_retention(records)
        self.assertEqual(len(result["retained"]), 3)
        self.assertEqual(len(result["delete"]), 2)

    def test_month_and_year_boundaries_use_utc_iso_calendar_periods(self) -> None:
        records = [
            _record(6, "2027-01-02T00:30:00+00:00"),
            _record(5, "2027-01-01T23:30:00+00:00"),
            _record(4, "2026-12-31T23:30:00+00:00"),
            _record(3, "2026-12-20T12:00:00+00:00"),
            _record(2, "2026-12-10T12:00:00+00:00"),
            _record(1, "2026-11-30T12:00:00+00:00"),
        ]
        result = select_retention(records)
        reasons = [reason for item in result["retained"] for reason in item["retention_reasons"]]
        self.assertEqual(sum(reason.startswith("daily:") for reason in reasons), 3)
        self.assertEqual(sum(reason.startswith("weekly:") for reason in reasons), 2)
        self.assertEqual(sum(reason.startswith("monthly:") for reason in reasons), 1)

    def test_corrupt_partial_and_active_reference_are_preserved(self) -> None:
        newest = _record(3, "2026-11-04T14:00:00+00:00")
        middle = _record(2, "2026-11-04T09:00:00+00:00")
        oldest = _record(1, "2026-11-04T04:00:00+00:00")
        corrupt = {"checkpoint_id": "bad", "status": "invalid", "error": "hash mismatch"}
        partial = {"checkpoint_id": ".partial", "status": "ambiguous"}
        result = select_retention(
            [newest, middle, oldest, corrupt, partial],
            {str(middle["checkpoint_id"])},
        )
        self.assertEqual(len(result["retained"]), 3)
        self.assertEqual(result["delete"], [])
        self.assertEqual(result["preserved_non_candidates"], [corrupt, partial])


class RetentionExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = self.root / "store"
        for name in ("checkpoints", "receipts", "state", "locks"):
            (self.store / name).mkdir(parents=True, exist_ok=True)
        source = self.root / "source.txt"
        source.write_text("fixture\n", encoding="utf-8")
        config_path = self.root / "config.toml"
        config_path.write_text(
            f'''[store]
root = "{self.store}"
mountpoint = "{self.root}"
minimum_free_bytes = 0

[retention]
enabled = true
daily = 3
weekly = 2
monthly = 1

[[files]]
name = "fixture"
source = "{source}"
restore = "{source}"
''',
            encoding="utf-8",
        )
        self.config = dataclasses.replace(
            load_config(config_path),
            retention=RetentionConfig(enabled=True),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_unsafe_symlink_candidate_is_rejected_and_never_selected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        checkpoint_id = "20261104T140000Z-0000000001"
        (self.store / "checkpoints" / checkpoint_id).symlink_to(outside, target_is_directory=True)
        records = inventory_checkpoints(self.config)
        self.assertEqual(records[0]["status"], "invalid")
        self.assertIn("real directory", records[0]["error"])

    def test_below_safety_floor_blocks_before_inventory_or_deletion(self) -> None:
        with patch(
            "rhizome_lifeboat.retention.validate_store",
            side_effect=RuntimeError("store has insufficient free space: 19 GiB < 20 GiB"),
        ), patch("rhizome_lifeboat.retention.inventory_checkpoints") as inventory:
            with self.assertRaisesRegex(RuntimeError, "insufficient free space"):
                retention_plan(self.config)
        inventory.assert_not_called()

    def test_interrupted_pruning_is_evidenced_and_blocks_retry(self) -> None:
        newest_id = "20261104T140000Z-0000000002"
        old_id = "20261104T090000Z-0000000001"
        (self.store / "checkpoints" / newest_id).mkdir()
        (self.store / "checkpoints" / old_id).mkdir()
        retained = {
            "checkpoint_id": newest_id,
            "created_at": "2026-11-04T14:00:00+00:00",
            "status": "verified",
            "manifest_sha256": "new-sha",
            "size_bytes": 200,
            "retention_reasons": ["daily:2026-11-04"],
        }
        deletion = {
            "checkpoint_id": old_id,
            "created_at": "2026-11-04T09:00:00+00:00",
            "status": "verified",
            "manifest_sha256": "old-sha",
            "size_bytes": 100,
            "deletion_reason": "redundant verified checkpoint on a retained UTC day",
        }
        plan = {
            "schema": "rhizome-lifeboat-retention-v1",
            "status": "dry-run",
            "generated_at": "2026-11-04T15:00:00+00:00",
            "policy": {"daily": 3, "weekly": 2, "monthly": 1, "timezone": "UTC"},
            "enabled": True,
            "disabled_by_marker": False,
            "active_references": [],
            "blockers": [],
            "retained": [retained],
            "delete": [deletion],
            "preserved_non_candidates": [],
            "missing_active_references": [],
        }
        with patch("rhizome_lifeboat.retention.retention_plan", return_value=plan), patch(
            "rhizome_lifeboat.retention.verify_checkpoint",
            return_value={"manifest_sha256": "old-sha"},
        ):
            with self.assertRaisesRegex(RuntimeError, "interrupted-pruning"):
                prune_checkpoints(
                    self.config,
                    dry_run=False,
                    required_new_checkpoint_id=newest_id,
                    fail_after_stage=True,
                )
        self.assertFalse((self.store / "checkpoints" / old_id).exists())
        self.assertEqual(len(list((self.store / "checkpoints").glob(f".pruning-{old_id}-*"))), 1)
        receipt_path = next((self.store / "receipts").glob("retention-*.json"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "interrupted")
        self.assertEqual(receipt["deletions"][0]["status"], "staged")
        self.assertTrue(_active_references(self.config)[1])

    def test_apply_refuses_when_approved_deletion_set_has_changed(self) -> None:
        newest_id = "20261104T140000Z-0000000002"
        plan = {
            "status": "dry-run",
            "policy": {"daily": 3, "weekly": 2, "monthly": 1, "timezone": "UTC"},
            "enabled": True,
            "disabled_by_marker": False,
            "blockers": [],
            "retained": [{
                "checkpoint_id": newest_id,
                "created_at": "2026-11-04T14:00:00+00:00",
                "status": "verified",
            }],
            "delete": [],
        }
        with patch("rhizome_lifeboat.retention.retention_plan", return_value=plan):
            with self.assertRaisesRegex(RuntimeError, "approved deletion set changed"):
                prune_checkpoints(
                    self.config,
                    dry_run=False,
                    required_new_checkpoint_id=newest_id,
                    expected_delete_ids={"20261104T090000Z-0000000001"},
                )
        self.assertEqual(list((self.store / "receipts").glob("retention-*.json")), [])

    def test_controller_lock_serialises_retention_with_checkpoint_and_recovery(self) -> None:
        lock_path = self.store / "locks" / "controller.lock"
        ready = multiprocessing.Event()
        release = multiprocessing.Event()
        holder = multiprocessing.Process(target=_hold_lock, args=(str(lock_path), ready, release))
        holder.start()
        self.assertTrue(ready.wait(2))
        result: list[dict[str, object]] = []
        empty_plan = {"status": "dry-run", "retained": [], "delete": []}
        with patch("rhizome_lifeboat.retention.retention_plan", return_value=empty_plan):
            worker = threading.Thread(
                target=lambda: result.append(prune_checkpoints(self.config, dry_run=True)),
                daemon=True,
            )
            worker.start()
            time.sleep(0.2)
            self.assertEqual(result, [])
            release.set()
            worker.join(2)
        holder.join(2)
        self.assertEqual(holder.exitcode, 0)
        self.assertEqual(result, [empty_plan])


if __name__ == "__main__":
    unittest.main()
