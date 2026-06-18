import subprocess
import sys
from pathlib import Path

import pytest

from research.etf_momentum_rotation import (
    MomentumRotationConfig,
    evaluate_snapshot,
    load_rotation_csv,
    render_text,
)


def _prices(start, steps):
    prices = [float(start)]
    for step in steps:
        prices.append(prices[-1] * (1 + step))
    return prices


def _bar(prices, amount=None):
    bar = {
        'close': prices[-1],
        'prices': prices,
        'volume': 1000000,
    }
    if amount is not None:
        bar['amount'] = amount
    return bar


def test_evaluate_snapshot_selects_positive_momentum_low_volatility_leader():
    config = MomentumRotationConfig(
        momentum_window=3,
        confirm_window=2,
        volatility_window=2,
        min_history_days=4,
        max_holdings=1,
    )
    snapshot = {
        'date': '2026-01-05',
        'symbols': {
            '510300': _bar([10.0, 10.5, 11.0, 11.5]),
            '510500': _bar([10.0, 10.2, 10.4, 10.5]),
            '159915': _bar([10.0, 9.8, 9.7, 9.6]),
        },
    }

    result = evaluate_snapshot(snapshot, config)

    assert result['selected'] == ['510300']
    assert result['ranked'][0]['symbol'] == '510300'
    assert result['ranked'][0]['momentum'] > 0
    assert any(
        rejection['symbol'] == '159915'
        and rejection['reason'] == 'non_positive_60d_momentum'
        for rejection in result['rejections']
    )


def test_evaluate_snapshot_reports_insufficient_history():
    config = MomentumRotationConfig(
        momentum_window=3,
        confirm_window=2,
        volatility_window=2,
        min_history_days=4,
    )

    result = evaluate_snapshot({
        'date': '2026-01-05',
        'symbols': {'510300': _bar([10.0, 10.1])},
    }, config)

    assert result['selected'] == []
    assert result['rejections'] == [{
        'symbol': '510300',
        'reason': 'insufficient_history len=2 need=4',
    }]


def test_evaluate_snapshot_can_apply_amount_filter():
    config = MomentumRotationConfig(
        momentum_window=3,
        confirm_window=2,
        volatility_window=2,
        min_history_days=4,
        min_avg_amount=1000,
    )

    result = evaluate_snapshot({
        'date': '2026-01-05',
        'symbols': {
            '510300': _bar([10.0, 10.5, 11.0, 11.5], amount=999),
        },
    }, config)

    assert result['rejections'][0]['reason'].startswith('low_amount')


def test_load_rotation_csv_and_render_text(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-05,510300,11.5,10|10.5|11|11.5,1000000,2000\n'
        '2026-01-05,510500,10.5,10|10.2|10.4|10.5,1000000,2000\n',
        encoding='utf-8',
    )

    history = load_rotation_csv(str(history_file))
    result = evaluate_snapshot(history[0], MomentumRotationConfig(
        momentum_window=3,
        confirm_window=2,
        volatility_window=2,
        min_history_days=4,
        max_holdings=1,
    ))
    output = render_text([result])

    assert 'date=2026-01-05' in output
    assert 'selected=510300' in output
    assert 'ranked:' in output


def test_cli_evaluate_etf_momentum_rotation_outputs_diagnostics(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume\n'
        '2026-01-05,510300,11.5,10|10.5|11|11.5,1000000\n'
        '2026-01-05,159915,9.6,10|9.8|9.7|9.6,1000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('scripts') / 'evaluate_etf_momentum_rotation.py'),
            '--history',
            str(history_file),
            '--momentum-window',
            '3',
            '--confirm-window',
            '2',
            '--volatility-window',
            '2',
            '--min-history-days',
            '4',
            '--rebalance-step',
            '1',
            '--limit',
            '1',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert 'selected=510300' in completed.stdout
    assert '159915: non_positive_60d_momentum' in completed.stdout
