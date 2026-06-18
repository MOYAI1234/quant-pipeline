import subprocess
import sys
from pathlib import Path

from backtest.runner import RotationBacktestRunner
from research.etf_momentum_rotation import (
    ETFMomentumRotationBacktestStrategy,
    MomentumRotationConfig,
    backtest_diagnostics,
)


def _bar(prices, amount=100000000):
    return {
        'close': prices[-1],
        'prices': prices,
        'volume': 1000000,
        'amount': amount,
    }


def test_etf_momentum_rotation_backtest_buys_and_rotates():
    history = [
        {
            'date': '2026-01-01',
            'symbols': {
                '510300': _bar([10.0, 11.0, 12.0, 13.0]),
                '510500': _bar([10.0, 10.0, 10.0, 10.1]),
                '159915': _bar([10.0, 9.8, 9.7, 9.6]),
            },
        },
        {
            'date': '2026-01-02',
            'symbols': {
                '510300': _bar([10.0, 10.0, 10.0, 9.0]),
                '510500': _bar([10.0, 11.0, 12.0, 14.0]),
                '159915': _bar([10.0, 9.9, 9.8, 9.7]),
            },
        },
    ]
    strategy = ETFMomentumRotationBacktestStrategy(
        ['510300', '510500', '159915'],
        MomentumRotationConfig(
            momentum_window=3,
            confirm_window=2,
            volatility_window=2,
            min_history_days=4,
            max_holdings=1,
        ),
        rebalance_step=1,
    )

    runner = RotationBacktestRunner(strategy, {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
        'min_commission': 5,
    })
    result = runner.run(history)

    assert [trade['action'] for trade in result['trades']] == [
        'buy',
        'sell',
        'buy',
    ]
    assert result['trades'][0]['symbol'] == '510300'
    assert result['trades'][-1]['symbol'] == '510500'
    assert result['portfolio']['position_count'] == 1
    assert '510500' in result['portfolio']['positions']

    diagnostics = backtest_diagnostics(runner.strategy)
    assert diagnostics['evaluation_count'] == 2
    assert diagnostics['selected_count'] == 2


def test_cli_backtest_etf_momentum_rotation_outputs_report(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-01,510300,13,10|11|12|13,1000000,100000000\n'
        '2026-01-01,510500,10.1,10|10|10|10.1,1000000,100000000\n'
        '2026-01-02,510300,9,10|10|10|9,1000000,100000000\n'
        '2026-01-02,510500,14,10|11|12|14,1000000,100000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('scripts') / 'backtest_etf_momentum_rotation.py'),
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
            '--max-holdings',
            '1',
            '--rebalance-step',
            '1',
            '--initial-capital',
            '100000',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - ETF-MOM-ROT-001 本地回测' in completed.stdout
    assert '## ETF-MOM-ROT-001 因子诊断' in completed.stdout
    assert '- 有候选次数: 2' in completed.stdout
