import subprocess
import sys
from pathlib import Path

import pytest

from backtest.runner import (
    BacktestRunner,
    RotationBacktestRunner,
    filter_history_by_date,
    load_history_csv,
    sample_grid_history,
    sample_rotation_history,
    _trade_outcome_stats,
)
from strategy.grid_strategy import GridStrategy
from strategy.rotation_strategy import RotationStrategy


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


def _rotation_strategy():
    return RotationStrategy({
        'name': '测试轮动回测',
        'symbol': '510300',
        'etf_pool': ['510300', '510500', '159915'],
        'lookback': 3,
        'top_n': 1,
        'rebalance_days': 0,
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
    assert result['closed_trade_count'] == 1
    assert result['winning_trade_count'] == 1
    assert result['win_rate'] == 1.0
    assert result['realized_pnl'] > 0
    assert result['total_return'] > 0
    assert result['max_drawdown'] >= 0
    assert len(result['equity_curve']) == 3
    assert '510300' not in result['portfolio']['positions']


def test_trade_outcome_stats_uses_net_profit_for_win_classification():
    stats = _trade_outcome_stats([
        {
            'action': 'sell',
            'symbol': '510300',
            'profit': 1.0,
            'entry_commission': 3.0,
        },
    ])

    assert stats['closed_trade_count'] == 1
    assert stats['winning_trade_count'] == 0
    assert stats['win_rate'] == 0.0


def test_rotation_backtest_runner_buys_then_rotates_to_new_leader():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run(sample_rotation_history())

    assert result['strategy'] == '测试轮动回测'
    assert result['symbol'] == '510300,510500,159915'
    # day1 买入 leader1；day2 卖出 leader1 并买入 leader2。
    assert result['trade_count'] == 3
    assert result['closed_trade_count'] == 1
    assert result['winning_trade_count'] == 0
    assert result['win_rate'] == 0.0
    assert len(result['equity_curve']) == 2
    assert '510300' not in result['portfolio']['positions']
    assert '510500' in result['portfolio']['positions']
    assert runner.strategy.selected_etfs == ['510500']
    assert len(runner.strategy.trades) == 3


def test_rotation_backtest_runner_uses_snapshot_dates_for_rebalance_windows():
    strategy = RotationStrategy({
        'name': '测试轮动日期',
        'symbol': '510300',
        'etf_pool': ['510300', '510500'],
        'lookback': 3,
        'top_n': 1,
        'rebalance_days': 10,
    })
    runner = RotationBacktestRunner(strategy, {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })
    history = [
        {
            'date': '2026-01-01',
            'symbols': {
                '510300': {'close': 12.0, 'prices': [10.0, 11.0, 12.0]},
                '510500': {'close': 9.0, 'prices': [10.0, 9.5, 9.0]},
            },
        },
        {
            'date': '2026-01-05',
            'symbols': {
                '510300': {'close': 11.5, 'prices': [11.0, 12.0, 11.5]},
                '510500': {'close': 12.0, 'prices': [9.0, 10.0, 12.0]},
            },
        },
        {
            'date': '2026-01-20',
            'symbols': {
                '510300': {'close': 11.0, 'prices': [12.0, 11.5, 11.0]},
                '510500': {'close': 13.0, 'prices': [10.0, 12.0, 13.0]},
            },
        },
    ]

    result = runner.run(history)

    assert result['trade_count'] == 3
    assert '510300' not in result['portfolio']['positions']
    assert '510500' in result['portfolio']['positions']
    assert runner.strategy.last_rebalance.isoformat() == '2026-01-20T00:00:00'


def test_rotation_backtest_runner_rejects_missing_symbol_price():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    with pytest.raises(ValueError, match='rotation history 中 510300 缺少有效价格'):
        runner.run([{
            'date': '2026-01-01',
            'symbols': {
                '510300': {'prices': [10.0, 11.0, 12.0]},
                '510500': {'close': 9.0, 'prices': [10.0, 9.5, 9.0]},
            },
        }])


def test_backtest_runner_skips_grid_order_when_bar_does_not_touch_limit_price():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run([{
        'date': '2026-01-01',
        'open': 4.00,
        'high': 4.02,
        'low': 3.92,
        'close': 3.95,
        'volume': 1000000,
        'amount': 3950000,
    }])

    assert result['trade_count'] == 0
    assert result['final_value'] == result['initial_capital']
    assert '510300' not in result['portfolio']['positions']
    assert runner.strategy.grid_ledger[3.9]['bought'] is False
    assert len(runner.strategy.trades) == 0


def test_backtest_runner_executes_grid_order_when_bar_wicks_through_limit_price():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run([{
        'date': '2026-01-01',
        'open': 4.00,
        'high': 4.05,
        'low': 3.90,
        'close': 4.05,
        'volume': 1000000,
        'amount': 4050000,
    }])

    assert result['trade_count'] == 1
    assert result['portfolio']['positions']['510300']['avg_price'] == 3.9
    assert runner.strategy.grid_ledger[3.9]['bought'] is True


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
    assert first_result['closed_trade_count'] == 0
    assert first_result['win_rate'] == 0.0
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
    assert result['closed_trade_count'] == 0
    assert result['win_rate'] == 0.0
    assert result['equity_curve'][0]['total_value'] < result['initial_capital']
    assert result['max_drawdown'] > 0


def test_backtest_runner_rejects_empty_history():
    runner = BacktestRunner(_grid_strategy())

    with pytest.raises(ValueError, match='history 不能为空'):
        runner.run([])


def test_backtest_runner_rejects_non_positive_initial_capital():
    runner = BacktestRunner(_grid_strategy(), {'initial_capital': 0})

    with pytest.raises(ValueError, match='initial_capital 必须大于 0'):
        runner.run(sample_grid_history())


def test_filter_history_by_date_keeps_inclusive_range():
    filtered = filter_history_by_date(
        sample_grid_history(),
        start_date='2026-01-02',
        end_date='2026-01-03',
    )

    assert [bar['date'] for bar in filtered] == [
        '2026-01-02',
        '2026-01-03',
    ]


def test_filter_history_by_date_normalizes_history_dates_before_comparing():
    history = [
        {
            'date': '2026-1-2',
            'open': 4.0,
            'high': 4.1,
            'low': 3.9,
            'close': 4.0,
            'volume': 1000,
            'amount': 4000.0,
        },
    ]

    filtered = filter_history_by_date(
        history,
        start_date='2026-01-01',
        end_date='2026-01-31',
    )

    assert filtered == history


def test_filter_history_by_date_rejects_empty_range():
    with pytest.raises(ValueError, match='指定日期区间内没有历史行情'):
        filter_history_by_date(
            sample_grid_history(),
            start_date='2026-02-01',
            end_date='2026-02-28',
        )


def test_filter_history_by_date_rejects_reversed_range():
    with pytest.raises(ValueError, match='--start-date 不能晚于 --end-date'):
        filter_history_by_date(
            sample_grid_history(),
            start_date='2026-01-03',
            end_date='2026-01-02',
        )


def test_filter_history_by_date_rejects_invalid_date_format():
    with pytest.raises(ValueError, match='--start-date 必须是 YYYY-MM-DD'):
        filter_history_by_date(
            sample_grid_history(),
            start_date='2026-1-2',
        )


def test_filter_history_by_date_rejects_empty_date_bound():
    with pytest.raises(ValueError, match='--start-date 必须是 YYYY-MM-DD'):
        filter_history_by_date(
            sample_grid_history(),
            start_date='',
        )


def test_filter_history_by_date_rejects_missing_history_date():
    with pytest.raises(ValueError, match='history 行日期必须是 YYYY-MM-DD'):
        filter_history_by_date([{'close': 4.0}])


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
    assert '- 胜率: 100.00%' in completed.stdout


def test_cli_backtest_date_range_limits_report_period():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--start-date',
            '2026-01-02',
            '--end-date',
            '2026-01-03',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '- 区间: 2026-01-02 至 2026-01-03' in completed.stdout


def test_cli_rotation_backtest_smoke_outputs_markdown_report():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - 轮动回测' in completed.stdout
    assert '- 标的池: 510300,510500,159915' in completed.stdout
    assert '- 交易次数: 3' in completed.stdout
    assert '- 胜率: 0.00%' in completed.stdout


def test_cli_rotation_backtest_date_range_limits_report_period():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--start-date',
            '2026-01-02',
            '--end-date',
            '2026-01-02',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '- 区间: 2026-01-02 至 2026-01-02' in completed.stdout


def test_cli_rotation_backtest_rejects_unknown_sample_symbol():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--etf-pool',
            '510300,UNKNOWN',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert 'rotation 内置样例不包含 ETF: UNKNOWN' in completed.stderr


def test_cli_rotation_backtest_explains_history_is_not_supported_yet():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--history',
            str(Path('history.csv')),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert 'CSV 历史行情将在后续版本支持' in completed.stderr


def test_cli_backtest_rejects_reversed_date_range():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--start-date',
            '2026-01-03',
            '--end-date',
            '2026-01-02',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert '--start-date 不能晚于 --end-date' in completed.stderr


def test_cli_backtest_rejects_invalid_date_format():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--start-date',
            '2026-1-2',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert '--start-date 必须是 YYYY-MM-DD' in completed.stderr


def test_cli_backtest_rejects_empty_date_format():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--start-date',
            '',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert '--start-date 必须是 YYYY-MM-DD' in completed.stderr


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
