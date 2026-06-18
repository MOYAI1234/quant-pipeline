"""Generate and verify deterministic backtest delivery artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ('grid', 'rotation')
REPORT_TITLES = {
    'grid': '# 回测报告 - 网格回测',
    'rotation': '# 回测报告 - 轮动回测',
}
CSV_SCHEMAS = {
    'equity.csv': (
        'date', 'total_value', 'pnl', 'pnl_percent', 'period_return', 'drawdown',
    ),
    'portfolio.csv': (
        'date', 'cash', 'position_count', 'positions_market_value', 'total_value',
        'pnl', 'pnl_percent', 'realized_pnl', 'unrealized_pnl',
        'total_value_delta',
    ),
    'trades.csv': (
        'timestamp', 'action', 'symbol', 'price', 'shares', 'requested_shares',
        'partial_fill', 'amount', 'commission', 'entry_commission', 'profit',
        'net_profit',
    ),
    'positions.csv': (
        'date', 'symbol', 'shares', 'avg_price', 'cost', 'commission',
        'current_price', 'market_value', 'unrealized_pnl',
    ),
    'rejections.csv': (
        'timestamp', 'action', 'symbol', 'price', 'shares', 'amount', 'reason',
        'signal_reason',
    ),
}
NON_EMPTY_CSVS = frozenset(CSV_SCHEMAS) - {'rejections.csv'}


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Generate and verify deterministic backtest delivery artifacts.',
    )
    parser.add_argument(
        '--output-dir',
        help='retain the verified artifacts and manifest in this directory',
    )
    parser.add_argument(
        '--strategy',
        action='append',
        choices=STRATEGIES,
        help='strategy to verify; may be repeated (default: both)',
    )
    args = parser.parse_args()

    strategies = tuple(dict.fromkeys(args.strategy or STRATEGIES))
    with ExitStack() as stack:
        if args.output_dir:
            output_root = _resolve_output_dir(args.output_dir)
            output_root.mkdir(parents=True, exist_ok=True)
        else:
            output_root = Path(stack.enter_context(
                tempfile.TemporaryDirectory(prefix='quant-backtest-artifacts-'),
            ))
        comparison_root = Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix='quant-backtest-recheck-'),
        ))

        manifest = {'version': 1, 'strategies': {}}
        for strategy in strategies:
            primary_dir = output_root / strategy
            comparison_dir = comparison_root / strategy
            _run_backtest(strategy, primary_dir)
            _run_backtest(strategy, comparison_dir)
            primary = _validate_artifacts(strategy, primary_dir)
            _validate_artifacts(strategy, comparison_dir)
            _compare_artifacts(primary_dir, comparison_dir)
            manifest['strategies'][strategy] = primary
            print(f'{strategy}: 6 artifacts verified and reproducible')

        if args.output_dir:
            manifest_path = output_root / 'manifest.json'
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8',
            )
            print(f'manifest: {manifest_path}')

    print('Backtest artifact verification passed.')
    return 0


def _resolve_output_dir(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _run_backtest(strategy: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        'cli/commands.py',
        'backtest',
        '--strategy',
        strategy,
        '--report-output',
        str(output_dir / 'report.md'),
        '--equity-output',
        str(output_dir / 'equity.csv'),
        '--portfolio-output',
        str(output_dir / 'portfolio.csv'),
        '--trades-output',
        str(output_dir / 'trades.csv'),
        '--positions-output',
        str(output_dir / 'positions.csv'),
        '--rejections-output',
        str(output_dir / 'rejections.csv'),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        raise RuntimeError(
            f'{strategy} backtest failed with exit code {completed.returncode}'
        )


def _validate_artifacts(strategy: str, output_dir: Path) -> dict:
    report_path = output_dir / 'report.md'
    report = report_path.read_text(encoding='utf-8')
    if not report.startswith(f'{REPORT_TITLES[strategy]}\n'):
        raise ValueError(f'{strategy} report has an unexpected heading')

    artifacts = {
        'report.md': {
            'rows': len(report.splitlines()),
            'sha256': _sha256(report_path),
        },
    }
    for filename, expected_fields in CSV_SCHEMAS.items():
        path = output_dir / filename
        with path.open(newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            if tuple(reader.fieldnames or ()) != expected_fields:
                raise ValueError(
                    f'{strategy} {filename} schema mismatch: {reader.fieldnames}'
                )
            rows = list(reader)
        if filename in NON_EMPTY_CSVS and not rows:
            raise ValueError(f'{strategy} {filename} must contain data rows')
        if filename == 'portfolio.csv':
            _validate_portfolio_rows(strategy, rows)
        artifacts[filename] = {
            'rows': len(rows),
            'sha256': _sha256(path),
        }
    return artifacts


def _validate_portfolio_rows(strategy: str, rows: list[dict]) -> None:
    for index, row in enumerate(rows, start=2):
        cash = float(row['cash'])
        positions_value = float(row['positions_market_value'])
        total_value = float(row['total_value'])
        recorded_delta = float(row['total_value_delta'])
        calculated_delta = cash + positions_value - total_value
        if abs(recorded_delta) > 1e-6 or abs(calculated_delta) > 1e-6:
            raise ValueError(
                f'{strategy} portfolio.csv row {index} has inconsistent total value'
            )


def _compare_artifacts(primary_dir: Path, comparison_dir: Path) -> None:
    filenames = ('report.md', *CSV_SCHEMAS)
    for filename in filenames:
        if (primary_dir / filename).read_bytes() != (
            comparison_dir / filename
        ).read_bytes():
            raise ValueError(f'{filename} is not reproducible')


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    raise SystemExit(main())
