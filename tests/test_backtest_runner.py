import subprocess
import sys

import pytest

from backtest.runner import BacktestRunner, load_history_csv, sample_grid_history
from strategy.grid_strategy import GridStrategy


def _grid_strategy():
    return GridStrategy({
        'name': '测试回测网格',
        'symbol': '510300',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })


def test_backtest_runner_executes_grid_buy_sell_cycle():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run(sample_grid_history())

    assert result['strategy'] == '测试回测网格'
    assert result['symbol'] == '510300'
    assert result['trade_count'] == 2
    assert result['realized_pnl'] > 0
    assert result['total_return'] > 0
    assert result['max_drawdown'] >= 0
    assert len(result['equity_curve']) == 3
    assert '510300' not in result['portfolio']['positions']


def test_backtest_runner_rejects_empty_history():
    runner = BacktestRunner(_grid_strategy())

    with pytest.raises(ValueError, match='history 不能为空'):
        runner.run([])


def test_load_history_csv_reads_basic_bar_fields(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n'
        '2026-01-01,4.0,4.1,3.9,4.05,1000,4050\n',
        encoding='utf-8',
    )

    rows = load_history_csv(str(history_file))

    assert rows == [{
        'date': '2026-01-01',
        'open': 4.0,
        'high': 4.1,
        'low': 3.9,
        'close': 4.05,
        'volume': 1000,
        'amount': 4050.0,
    }]


def test_cli_backtest_smoke_outputs_markdown_report():
    completed = subprocess.run(
        [sys.executable, 'cli\\commands.py', 'backtest', '--strategy', 'grid'],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - 网格回测' in completed.stdout
    assert '- 交易次数: 2' in completed.stdout
