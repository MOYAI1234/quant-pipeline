import subprocess
import sys
from pathlib import Path

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


def test_backtest_runner_resets_state_between_runs():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    first_result = runner.run(sample_grid_history())
    second_result = runner.run(sample_grid_history())

    assert first_result['trade_count'] == 2
    assert second_result['trade_count'] == 2
    assert len(second_result['equity_curve']) == 3
    assert second_result['start_date'] == '2026-01-01'
    assert second_result['final_value'] == first_result['final_value']


def test_backtest_runner_resets_strategy_state_between_runs_with_open_position():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })
    buy_only_history = [{
        'date': '2026-01-01',
        'open': 3.90,
        'high': 3.90,
        'low': 3.90,
        'close': 3.90,
        'volume': 1000000,
        'amount': 3900000,
    }]

    first_result = runner.run(buy_only_history)
    second_result = runner.run(buy_only_history)

    assert first_result['trade_count'] == 1
    assert second_result['trade_count'] == 1
    assert len(second_result['portfolio']['positions']) == 1
    assert runner.strategy.grid_ledger[3.9]['bought'] is True
    assert len(runner.strategy.trades) == 1


def test_backtest_runner_drawdown_starts_from_initial_capital():
    strategy = GridStrategy({
        'name': '测试亏损网格',
        'symbol': '510300',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })
    runner = BacktestRunner(strategy, {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run([
        {
            'date': '2026-01-01',
            'open': 3.90,
            'high': 3.90,
            'low': 3.90,
            'close': 3.90,
            'volume': 1000000,
            'amount': 3900000,
        },
    ])

    assert result['trade_count'] == 1
    assert result['equity_curve'][0]['total_value'] < result['initial_capital']
    assert result['max_drawdown'] > 0


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


def test_load_history_csv_rejects_missing_file(tmp_path):
    missing_file = tmp_path / 'missing.csv'

    with pytest.raises(FileNotFoundError, match='历史行情 CSV 不存在'):
        load_history_csv(str(missing_file))


def test_load_history_csv_rejects_empty_file(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text('', encoding='utf-8')

    with pytest.raises(ValueError, match='历史行情 CSV 不能为空'):
        load_history_csv(str(history_file))


def test_load_history_csv_rejects_missing_required_columns(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume\n'
        '2026-01-01,4.0,4.1,3.9,4.05,1000\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='历史行情 CSV 缺少字段: amount'):
        load_history_csv(str(history_file))


def test_load_history_csv_rejects_header_without_data_rows(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='历史行情 CSV 没有数据行'):
        load_history_csv(str(history_file))


def test_load_history_csv_rejects_invalid_numeric_fields(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n'
        '2026-01-01,4.0,4.1,3.9,bad,1000,4050\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='字段 close 不是有效数字'):
        load_history_csv(str(history_file))


def test_load_history_csv_rejects_fractional_integer_fields(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n'
        '2026-01-01,4.0,4.1,3.9,4.05,1000.9,4050\n',
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='字段 volume 不是有效整数'):
        load_history_csv(str(history_file))


def test_cli_backtest_smoke_outputs_markdown_report():
    completed = subprocess.run(
        [sys.executable, str(Path('cli') / 'commands.py'), 'backtest', '--strategy', 'grid'],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - 网格回测' in completed.stdout
    assert '- 交易次数: 2' in completed.stdout


@pytest.mark.parametrize('option,value', [
    ('--grid-size', '0'),
    ('--initial-capital', '-1'),
])
def test_cli_backtest_rejects_invalid_numeric_args(option, value):
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            option,
            value,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert option in completed.stderr
