"""Run an explicit TuShare reverse-proxy live drill.

The script requires local environment variables but never accepts secrets as
CLI arguments. Generated real-market CSV files are kept only when --output-dir
is provided.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN_ENV = 'TUSHARE_TOKEN'
API_URL_ENV = 'TUSHARE_API_URL'
RUN_ENV = 'RUN_TUSHARE_LIVE'


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Verify TuShare reverse-proxy live history and backtest loading.',
    )
    parser.add_argument(
        '--config',
        default='examples/configs/history-providers.local.example.json',
        help='provider config path',
    )
    parser.add_argument('--symbol', default='510300', help='single ETF symbol')
    parser.add_argument(
        '--etf-pool',
        default='510300,510500,159915',
        help='comma-separated rotation ETF pool',
    )
    parser.add_argument('--start-date', default='2026-01-05', help='YYYY-MM-DD')
    parser.add_argument('--end-date', default='2026-03-31', help='YYYY-MM-DD')
    parser.add_argument('--lookback', type=int, default=20)
    parser.add_argument(
        '--symbol-delay-seconds',
        type=float,
        default=1,
        help='delay between provider-backed rotation symbol requests',
    )
    parser.add_argument(
        '--output-dir',
        help='retain generated live CSV files in this directory',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='print the drill steps without running them',
    )
    args = parser.parse_args()

    checks = _build_checks(args, Path('<output-dir>'))
    if args.list:
        for name, command in checks:
            print(f'{name}: {_format_command(command)}')
        return 0

    missing_env = [name for name in (TOKEN_ENV, API_URL_ENV) if not os.getenv(name)]
    if missing_env:
        print(
            'Missing required environment variables: ' + ', '.join(missing_env),
            file=sys.stderr,
        )
        return 2

    env = os.environ.copy()
    env[RUN_ENV] = '1'
    with ExitStack() as stack:
        if args.output_dir:
            output_dir = _resolve_output_dir(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = Path(stack.enter_context(
                tempfile.TemporaryDirectory(prefix='quant-tushare-proxy-'),
            ))

        checks = _build_checks(args, output_dir)
        for name, command in checks:
            print(f'\n==> {name}: {_format_command(command)}', flush=True)
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            if completed.stdout:
                print(completed.stdout, end='')
            if completed.stderr:
                print(completed.stderr, end='', file=sys.stderr)
            if completed.returncode != 0:
                print(
                    f'\n{name} failed with exit code {completed.returncode}',
                    file=sys.stderr,
                )
                return completed.returncode
            if name == 'history-probe':
                _validate_probe_output(completed.stdout, args.symbol)

        _validate_export(output_dir / 'grid-history.csv')
        _validate_export(output_dir / 'rotation-history.csv')
        if args.output_dir:
            print(f'\nLive drill artifacts retained in: {output_dir}')

    print('\nTuShare reverse-proxy live drill passed.')
    return 0


def _build_checks(args: argparse.Namespace, output_dir: Path) -> list[tuple[str, list[str]]]:
    config_path = str(_resolve_path(args.config))
    grid_csv = str(output_dir / 'grid-history.csv')
    rotation_csv = str(output_dir / 'rotation-history.csv')
    return [
        (
            'tushare-live-test',
            [sys.executable, '-m', 'pytest', 'tests/test_tushare_history_provider_live.py', '-q'],
        ),
        (
            'history-probe',
            [
                sys.executable,
                'cli/commands.py',
                'history',
                'probe',
                '--config',
                config_path,
                '--symbol',
                args.symbol,
                '--start-date',
                args.start_date,
                '--end-date',
                args.start_date,
                '--json',
            ],
        ),
        (
            'history-export-grid',
            [
                sys.executable,
                'cli/commands.py',
                'history',
                'export-grid',
                '--config',
                config_path,
                '--symbol',
                args.symbol,
                '--start-date',
                args.start_date,
                '--end-date',
                args.end_date,
                '--output',
                grid_csv,
            ],
        ),
        (
            'history-export-rotation',
            [
                sys.executable,
                'cli/commands.py',
                'history',
                'export-rotation',
                '--config',
                config_path,
                '--etf-pool',
                args.etf_pool,
                '--start-date',
                args.start_date,
                '--end-date',
                args.end_date,
                '--lookback',
                str(args.lookback),
                '--symbol-delay-seconds',
                str(args.symbol_delay_seconds),
                '--output',
                rotation_csv,
            ],
        ),
        (
            'grid-backtest-load',
            [
                sys.executable,
                'cli/commands.py',
                'backtest',
                '--strategy',
                'grid',
                '--history',
                grid_csv,
                '--symbol',
                args.symbol,
                '--start-date',
                args.start_date,
                '--end-date',
                args.end_date,
                '--center-price',
                '4',
                '--grid-size',
                '0.03',
                '--grid-count',
                '6',
                '--shares-per-grid',
                '1000',
                '--max-volume-participation',
                '0.05',
            ],
        ),
        (
            'rotation-backtest-load',
            [
                sys.executable,
                'cli/commands.py',
                'backtest',
                '--strategy',
                'rotation',
                '--history',
                rotation_csv,
                '--etf-pool',
                args.etf_pool,
                '--start-date',
                args.start_date,
                '--end-date',
                args.end_date,
                '--lookback',
                str(args.lookback),
                '--top-n',
                '1',
                '--rebalance-days',
                '5',
                '--max-volume-participation',
                '0.05',
            ],
        ),
    ]


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _resolve_output_dir(value: str) -> Path:
    return _resolve_path(value)


def _validate_probe_output(stdout: str, symbol: str) -> None:
    result = json.loads(stdout)
    provider_status = result.get('provider_status') or {}
    if result.get('symbol') != symbol or result.get('row_count', 0) <= 0:
        raise ValueError('history probe did not return usable rows')
    if provider_status.get('last_history_provider') != 'tushare':
        raise ValueError('history probe did not use the TuShare provider')
    if provider_status.get('last_history_failures'):
        raise ValueError('history probe reported provider failures')


def _validate_export(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f'expected non-empty export: {path}')


def _format_command(command: list[str]) -> str:
    return ' '.join(command)


if __name__ == '__main__':
    raise SystemExit(main())
