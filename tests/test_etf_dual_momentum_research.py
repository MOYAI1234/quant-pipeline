import subprocess
import sys
from pathlib import Path

from backtest.runner import RotationBacktestRunner
from research.etf_dual_momentum import (
    DualMomentumConfig,
    ETFDualMomentumBacktestStrategy,
    backtest_diagnostics,
    evaluate_history,
    month_end_dates,
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
            'date': '2026-01-15',
            'symbols': {
                '510300': _bar([10.0, 10.1, 10.2, 10.3]),
                '518880': _bar([10.0, 10.0, 10.0, 10.0]),
            },
        },
        {
            'date': '2026-01-31',
            'symbols': {
                '510300': _bar([10.0, 11.0, 12.0, 13.0]),
                '518880': _bar([10.0, 10.0, 10.0, 10.1]),
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


def test_evaluate_history_uses_month_end_dual_momentum_signal():
    results = evaluate_history(
        _history(),
        DualMomentumConfig(
            lookback_days=3,
            min_history_days=4,
        ),
        ['510300'],
        ['518880'],
        rebalance_dates=month_end_dates(_history()),
    )

    assert [result['date'] for result in results] == [
        '2026-01-31',
        '2026-02-28',
    ]
    assert results[0]['regime'] == 'risk_on'
    assert results[0]['selected'] == ['510300']
    assert results[1]['regime'] == 'risk_off'
    assert results[1]['selected'] == ['518880']


def test_dual_momentum_backtest_buys_risk_then_rotates_to_defensive():
    strategy = ETFDualMomentumBacktestStrategy(
        ['510300'],
        ['518880'],
        DualMomentumConfig(
            lookback_days=3,
            min_history_days=4,
        ),
        rebalance_dates=month_end_dates(_history()),
    )
    runner = RotationBacktestRunner(strategy, {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
        'min_commission': 5,
    })

    result = runner.run(_history())

    assert [trade['action'] for trade in result['trades']] == [
        'buy',
        'sell',
        'buy',
    ]
    assert result['trades'][0]['symbol'] == '510300'
    assert result['trades'][-1]['symbol'] == '518880'
    assert '518880' in result['portfolio']['positions']

    diagnostics = backtest_diagnostics(runner.strategy)
    assert diagnostics['evaluation_count'] == 2
    assert diagnostics['regime_counts'] == {
        'risk_on': 1,
        'risk_off': 1,
    }


def test_cli_evaluate_etf_dual_momentum_outputs_diagnostics(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-31,510300,13,10|11|12|13,1000000,100000000\n'
        '2026-01-31,518880,10.1,10|10|10|10.1,1000000,100000000\n'
        '2026-02-28,510300,9,10|10|10|9,1000000,100000000\n'
        '2026-02-28,518880,14,10|11|12|14,1000000,100000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('scripts') / 'evaluate_etf_dual_momentum.py'),
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
            '--limit',
            '2',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert 'date=2026-01-31' in completed.stdout
    assert 'regime=risk_on' in completed.stdout
    assert 'selected=510300' in completed.stdout
    assert 'regime=risk_off' in completed.stdout
    assert 'selected=518880' in completed.stdout


def test_cli_backtest_etf_dual_momentum_outputs_report(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-31,510300,13,10|11|12|13,1000000,100000000\n'
        '2026-01-31,518880,10.1,10|10|10|10.1,1000000,100000000\n'
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
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - ETF-DUAL-MOM-002 本地回测' in completed.stdout
    assert '## ETF-DUAL-MOM-002 因子诊断' in completed.stdout
    assert '- 风险状态: risk_off=1, risk_on=1' in completed.stdout
