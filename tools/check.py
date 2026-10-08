#!/usr/bin/env python3
"""Run every bundled regression suite and report all failures in one place."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    suites = sorted((ROOT / 'tests').glob('test_*.py'))
    if not suites:
        print('FAIL: no test suites found', file=sys.stderr)
        return 1
    failures = []
    started = time.monotonic()
    for suite in suites:
        print(f'\nRunning {suite.name}', flush=True)
        result = subprocess.run([sys.executable, str(suite)], cwd=ROOT)
        if result.returncode:
            failures.append(suite.name)
    print(f'\n{len(suites) - len(failures)}/{len(suites)} suites passed in {time.monotonic() - started:.1f}s', flush=True)
    if failures:
        print('Failed: ' + ', '.join(failures), file=sys.stderr)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
