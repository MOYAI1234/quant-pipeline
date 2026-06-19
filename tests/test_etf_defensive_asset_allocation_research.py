import subprocess
import sys
from pathlib import Path

from backtest.runner import RotationBacktestRunner
from research.etf_defensive_asset_allocation import (
    DefensiveAssetAllocationConfig,
    ETFDefensiveAssetAllocationBacktestStrategy,
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
            'date': '2026-01-31',
            'symbols': {
                '510300': _bar([10.0, 11.0, 12.0, 13.0]),
                '510500': _bar([10.0, 10.5, 11.0, 12.0]),
                '518880': _bar([10.0, 10.0, 10.0, 10.1]),
            },
        },
        {
            'date': '2026-02-28',
            'symbols': {
                '510300': _bar([10.0, 10.0, 10.0, 9.0]),
                '510500': _bar([10.0, 9.8, 9.7, 9.6]),
                '518880': _bar([10.0, 11.0, 12.0, 14.0]),
            },
        },
    ]


def _config():
    return DefensiveAssetAllocationConfig(
        lookback_days=3,
        min_history_days=4,
        risk_holdings=2,
        defensive_holdings=1,
        canary_threshold=1.0,
        breadth_threshold=0.5,
    )


def test_evaluate_history_switches_from_risk_on_to_risk_off():
    results = evaluate_history(
        _history(),
        _config(),
        ['510300', '510500'],
        ['518880'],
        ['510300', '510500'],
        rebalance_dates=month_end_dates(_history()),
    )

    assert results[0]['regime'] == 'risk_on'
    assert results[0]['selected'] == ['510300', '510500']
    assert results[0]['canary_ratio'] == 1.0
    assert results[0]['breadth_ratio'] == 1.0

    assert results[1]['regime'] == 'risk_off'
    assert results[1]['selected'] == ['518880']
    assert results[1]['canary_ratio'] == 0.0
    assert results[1]['breadth_ratio'] == 0.0


def test_daa_backtest_buys_risk_then_rotates_to_defensive():
    strategy = ETFDefensiveAssetAllocationBacktestStrategy(
        ['510300', '510500'],
        ['518880'],
        ['510300', '510500'],
        _config(),
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
        'buy',
        'sell',
        'sell',
        'buy',
    ]
    assert result['trades'][0]['symbol'] == '510300'
    assert result['trades'][1]['symbol'] == '510500'
    assert result['trades'][-1]['symbol'] == '518880'
    assert '518880' in result['portfolio']['positions']

    diagnostics = backtest_diagnostics(runner.strategy)
    assert diagnostics['evaluation_count'] == 2
    assert diagnostics['regime_counts'] == {
        'risk_on': 1,
        'risk_off': 1,
    }


def test_cli_evaluate_etf_daa_outputs_diagnostics(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-31,510300,13,10|11|12|13,1000000,100000000\n'
        '2026-01-31,510500,12,10|10.5|11|12,1000000,100000000\n'
        '2026-01-31,518880,10.1,10|10|10|10.1,1000000,100000000\n'
        '2026-02-28,510300,9,10|10|10|9,1000000,100000000\n'
        '2026-02-28,510500,9.6,10|9.8|9.7|9.6,1000000,100000000\n'
        '2026-02-28,518880,14,10|11|12|14,1000000,100000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('scripts') / 'evaluate_etf_daa.py'),
            '--history',
            str(history_file),
            '--risk-assets',
            '510300,510500',
            '--defensive-assets',
            '518880',
            '--canary-assets',
            '510300,510500',
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

    assert 'regime=risk_on' in completed.stdout
    assert 'canary_ratio=1.0000' in completed.stdout
    assert 'selected=510300,510500' in completed.stdout
    assert 'regime=risk_off' in completed.stdout
    assert 'selected=518880' in completed.stdout


def test_cli_backtest_etf_daa_outputs_report(tmp_path):
    history_file = tmp_path / 'rotation.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume,amount\n'
        '2026-01-31,510300,13,10|11|12|13,1000000,100000000\n'
        '2026-01-31,510500,12,10|10.5|11|12,1000000,100000000\n'
        '2026-01-31,518880,10.1,10|10|10|10.1,1000000,100000000\n'
        '2026-02-28,510300,9,10|10|10|9,1000000,100000000\n'
        '2026-02-28,510500,9.6,10|9.8|9.7|9.6,1000000,100000000\n'
        '2026-02-28,518880,14,10|11|12|14,1000000,100000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('scripts') / 'backtest_etf_daa.py'),
            '--history',
            str(history_file),
            '--risk-assets',
            '510300,510500',
            '--defensive-assets',
            '518880',
            '--canary-assets',
            '510300,510500',
            '--lookback-days',
            '3',
            '--min-history-days',
            '4',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - ETF-DAA-003 本地回测' in completed.stdout
    assert '## ETF-DAA-003 因子诊断' in completed.stdout
    assert '- 风险状态: risk_off=1, risk_on=1' in completed.stdout
