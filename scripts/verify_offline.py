"""Run the offline research/simulator release checks."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


CHECKS = [
    ('compile', [sys.executable, '-m', 'compileall', '-q', '.']),
    ('pytest', [sys.executable, '-m', 'pytest', '-q']),
    ('health', [sys.executable, 'cli/commands.py', 'health', '--no-state']),
    ('diagnose', [sys.executable, 'cli/commands.py', 'diagnose', '--no-state']),
    (
        'daily-report',
        [sys.executable, 'cli/commands.py', 'report', '--type', 'daily', '--no-state'],
    ),
    ('grid-backtest', [sys.executable, 'cli/commands.py', 'backtest', '--strategy', 'grid']),
    (
        'rotation-backtest',
        [sys.executable, 'cli/commands.py', 'backtest', '--strategy', 'rotation'],
    ),
    (
        'backtest-artifacts',
        [sys.executable, 'scripts/verify_backtest_artifacts.py'],
    ),
    ('history-probe-help', [sys.executable, 'cli/commands.py', 'history', 'probe', '--help']),
    (
        'history-export-grid-help',
        [sys.executable, 'cli/commands.py', 'history', 'export-grid', '--help'],
    ),
    (
        'history-export-rotation-help',
        [sys.executable, 'cli/commands.py', 'history', 'export-rotation', '--help'],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Run offline checks for the research/simulator release.',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='print checks without running them',
    )
    args = parser.parse_args()

    if args.list:
        for name, command in CHECKS:
            print(f"{name}: {_format_command(command)}")
        return 0

    for name, command in CHECKS:
        print(f"\n==> {name}: {_format_command(command)}", flush=True)
        completed = subprocess.run(command, cwd=PROJECT_ROOT)
        if completed.returncode != 0:
            print(f"\n{name} failed with exit code {completed.returncode}", file=sys.stderr)
            return completed.returncode

    print('\nAll offline release checks passed.')
    return 0


def _format_command(command: list[str]) -> str:
    return ' '.join(command)


if __name__ == '__main__':
    raise SystemExit(main())
