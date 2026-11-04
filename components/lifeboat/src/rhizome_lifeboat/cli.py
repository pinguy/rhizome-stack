from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checkpoint import create_checkpoint, list_checkpoints, verify_checkpoint
from .audit import audit_config
from .config import load_config
from .health import diagnose, monitor_probe
from .drill import restore_drill
from .recovery import recover_automatically, undo_recovery
from .retention import prune_checkpoints
from .window import close_window, load_window, prepare_change


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rhizome-lifeboat")
    parser.add_argument("--config", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("checkpoint", help="create a verified checkpoint")
    create.add_argument("--reason", required=True)
    create.add_argument("--kind", choices=("manual", "scheduled", "pre-change"), default="manual")

    verify = subparsers.add_parser("verify", help="verify a checkpoint")
    verify.add_argument("checkpoint_id")

    subparsers.add_parser("list", help="list checkpoint candidates")
    prepare = subparsers.add_parser("prepare-change", help="checkpoint and open a bounded change window")
    prepare.add_argument("--reason", required=True)
    close = subparsers.add_parser("close-change", help="close the current change window")
    close.add_argument("--outcome", required=True)
    subparsers.add_parser("window", help="show current change-window state")
    subparsers.add_parser("diagnose", help="run independent health and classification checks")
    subparsers.add_parser("recover", help="apply policy-gated automatic recovery once")
    subparsers.add_parser("audit", help="read-only audit of checkpoint scope and store volume")
    subparsers.add_parser("retention-dry-run", help="verify and show the retention plan without deletion")
    retention_apply = subparsers.add_parser(
        "retention-apply",
        help="apply an approved plan using the latest newly verified checkpoint",
    )
    retention_apply.add_argument("new_checkpoint_id")
    retention_apply.add_argument("--expect-delete", action="append", required=True)
    drill = subparsers.add_parser("restore-drill", help="materialise and verify a disposable restore tree")
    drill.add_argument("checkpoint_id")
    drill.add_argument("--destination", required=True, type=Path)
    undo = subparsers.add_parser("undo", help="explicitly restore an incident's quarantined pre-recovery state")
    undo.add_argument("incident_id")
    subparsers.add_parser("monitor-check", help="minimal unprivileged Monit probe")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "checkpoint":
            _emit(create_checkpoint(config, args.reason, args.kind))
        elif args.command == "verify":
            _emit(verify_checkpoint(config, args.checkpoint_id))
        elif args.command == "list":
            _emit(list_checkpoints(config))
        elif args.command == "prepare-change":
            _emit(prepare_change(config, args.reason))
        elif args.command == "close-change":
            _emit(close_window(config, args.outcome))
        elif args.command == "window":
            _emit(load_window(config) or {"status": "none"})
        elif args.command == "diagnose":
            _emit(diagnose(config).as_dict())
        elif args.command == "recover":
            _emit(recover_automatically(config))
        elif args.command == "audit":
            _emit(audit_config(config))
        elif args.command == "retention-dry-run":
            _emit(prune_checkpoints(config, dry_run=True))
        elif args.command == "retention-apply":
            _emit(prune_checkpoints(
                config,
                dry_run=False,
                required_new_checkpoint_id=args.new_checkpoint_id,
                expected_delete_ids=set(args.expect_delete),
            ))
        elif args.command == "restore-drill":
            _emit(restore_drill(config, args.checkpoint_id, args.destination))
        elif args.command == "undo":
            _emit(undo_recovery(config, args.incident_id))
        elif args.command == "monitor-check":
            result = monitor_probe(config)
            _emit(result)
            return 0 if result["healthy"] else 1
        else:
            parser.error(f"unknown command: {args.command}")
        return 0
    except Exception as error:
        _emit({"status": "error", "error": str(error), "error_type": type(error).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(main())
