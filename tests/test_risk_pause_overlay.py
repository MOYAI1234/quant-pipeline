import subprocess
import sys
from pathlib import Path

from backtest.runner import RotationBacktestRunner
from research.etf_dual_momentum import (
    DualMomentumConfig,
    ETFDualMomentumBacktestStrategy,
    month_end_dates,
)
from research.risk_pause_overlay import (
    DrawdownPauseOverlayStrategy,
    overlay_diagnostics,
)


def _bar(prices, amount=100000000):
    return {
        'close': prices[-1],
        'prices': prices,
        'volume': 1000000,
        'amount': amount,
    }


def _history():
    return [
        {
            'date': '2026-01-31',
            'symbols': {
                '510300': _bar([10.0, 11.0, 12.0, 13.0]),
                '518880': _bar([10.0, 10.0, 10.0, 10.1]),
            },
        },
        {
            'date': '2026-02-10',
            'symbols': {
                '510300': _bar([10.0, 10.0, 10.0, 11.0]),
                '518880': _bar([10.0, 10.0, 10.0, 10.2]),
            },
        },
        {
            'date': '2026-02-20',
            'symbols': {
                '510300': _bar([10.0, 10.0, 10.0, 12.5]),
                '518880': _bar([10.0, 10.0, 10.0, 10.3]),
            },
        },
        {
            'date': '2026-02-28',
            'symbols': {
                '510300': _bar([10.0, 10.0, 10.0, 9.0]),
                '518880': _bar([10.0, 11.0, 12.0, 14.0]),
            },
        },
    ]


def _dual_strategy(history):
    return ETFDualMomentumBacktestStrategy(
        ['510300'],
        ['518880'],
        DualMomentumConfig(
            lookback_days=3,
            min_history_days=4,
        ),
        rebalance_dates=month_end_dates(history),
    )


def test_drawdown_pause_overlay_sells_mid_month_and_releases_on_next_rebalance():
    history = _history()
    strategy = DrawdownPauseOverlayStrategy(
        _dual_strategy(history),
        max_drawdown=0.1,
        release_dates=month_end_dates(history),
    )
    runner = RotationBacktestRunner(strategy, {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
        'min_commission': 5,
    })

    result = runner.run(history)

    sell_trades = [
        trade for trade in result['trades']
        if trade['action'] == 'sell'
    ]
    assert sell_trades[0]['timestamp'] == '2026-02-10'
    assert sell_trades[0]['symbol'] == '510300'
    assert sell_trades[0]['shares'] > 0

    diagnostics = overlay_diagnostics(runner.strategy)
    assert diagnostics['pause_count'] == 1
    assert diagnostics['release_count'] == 1
    assert diagnostics['pauses'][0]['date'] == '2026-02-10'
    assert diagnostics['pauses'][0]['drawdown'] >= 0.1


def test_cli_backtest_dual_momentum_with_drawdown_pause_outputs_overlay(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-31,510300,13,10|11|12|13,1000000,100000000\n'
        '2026-01-31,518880,10.1,10|10|10|10.1,1000000,100000000\n'
        '2026-02-10,510300,11,10|10|10|11,1000000,100000000\n'
        '2026-02-10,518880,10.2,10|10|10|10.2,1000000,100000000\n'
        '2026-02-28,510300,9,10|10|10|9,1000000,100000000\n'
        '2026-02-28,518880,14,10|11|12|14,1000000,100000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('scripts') / 'backtest_etf_dual_momentum.py'),
            '--history',
            str(history_file),
            '--risk-assets',
            '510300',
            '--defensive-assets',
            '518880',
            '--lookback-days',
            '3',
            '--min-history-days',
            '4',
            '--drawdown-pause',
            '0.1',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '## 回撤暂停诊断' in completed.stdout
    assert '- 暂停触发次数: 1' in completed.stdout
    assert '2026-02-10' in completed.stdout
