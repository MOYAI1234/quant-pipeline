import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from backtest.runner import (
    BacktestExecutionModel,
    BacktestRunner,
    RotationBacktestRunner,
    filter_history_by_date,
    load_history_csv,
    load_rotation_history_csv,
    load_rotation_history_json,
    sample_grid_history,
    sample_rotation_history,
    write_equity_curve_csv,
    write_positions_csv,
    write_rejected_orders_csv,
    write_trades_csv,
    _build_volume_limits,
    _consume_signal_volume,
    _drawdown_stats,
    _signal_within_volume_limit,
    _trade_cost_stats,
    _trade_outcome_stats,
)
from backtest.trading_calendar import TradingCalendar
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
    assert result['total_commission'] == pytest.approx(2.4)
    assert result['commission_ratio'] == pytest.approx(0.000024)
    assert result['realized_pnl'] > 0
    assert result['total_return'] > 0
    assert result['max_drawdown'] >= 0
    assert result['max_drawdown_start'] == '2026-01-01'
    assert result['max_drawdown_end'] == '2026-01-01'
    assert len(result['equity_curve']) == 3
    assert result['equity_curve'][0]['period_return'] == pytest.approx(0.0)
    assert result['equity_curve'][0]['drawdown'] == pytest.approx(0.0)
    assert result['equity_curve'][1]['drawdown'] >= 0
    assert [trade['action'] for trade in result['trades']] == ['buy', 'sell']
    assert [trade['timestamp'] for trade in result['trades']] == [
        '2026-01-02',
        '2026-01-03',
    ]
    assert '510300' not in result['portfolio']['positions']


def test_backtest_runner_applies_slippage_to_execution_prices():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
        'slippage_rate': 0.01,
    })

    result = runner.run(sample_grid_history())

    buy_trade, sell_trade = runner.executor.trades
    assert buy_trade['price'] == pytest.approx(3.9 * 1.01)
    assert sell_trade['price'] == pytest.approx(4.1 * 0.99)
    assert runner.strategy.trades[0]['price'] == pytest.approx(3.9 * 1.01)
    assert runner.strategy.trades[1]['price'] == pytest.approx(4.1 * 0.99)
    assert result['slippage_rate'] == 0.01
    assert result['portfolio']['positions'] == {}
    assert runner.strategy.grid_ledger[3.9]['bought'] is False


def test_backtest_runner_rejects_order_above_volume_participation_limit():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'max_volume_participation': 0.1,
    })
    bar = dict(sample_grid_history()[1], volume=5000)

    result = runner.run([bar])

    assert result['trade_count'] == 0
    assert result['rejected_order_count'] == 1
    assert result['rejection_reasons'] == {'volume_limit': 1}
    assert result['rejected_orders'] == [{
        'timestamp': '2026-01-02',
        'action': 'buy',
        'symbol': '510300',
        'price': 3.9,
        'shares': 1000,
        'amount': 3900.0,
        'reason': 'volume_limit',
        'signal_reason': '网格买入，价格3.9',
    }]
    assert result['max_volume_participation'] == 0.1
    assert runner.strategy.grid_ledger[3.9]['bought'] is False


def test_backtest_runner_executes_order_at_volume_participation_limit():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'max_volume_participation': 0.1,
    })
    bar = dict(sample_grid_history()[1], volume=10000)

    result = runner.run([bar])

    assert result['trade_count'] == 1
    assert result['trades'][0]['shares'] == 1000
    assert result['max_volume_participation'] == 0.1


def test_backtest_runner_records_executor_rejection():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 1000,
    })

    result = runner.run([sample_grid_history()[1]])

    assert result['trade_count'] == 0
    assert result['rejected_order_count'] == 1
    assert result['rejection_reasons'] == {'executor_rejected': 1}
    assert result['rejected_orders'][0]['reason'] == 'executor_rejected'
    assert result['rejected_orders'][0]['timestamp'] == '2026-01-02'


@pytest.mark.parametrize('value', [0, -0.1, 1.1, math.nan, True])
def test_backtest_runner_rejects_invalid_volume_participation(value):
    with pytest.raises(
        ValueError,
        match='max_volume_participation 必须大于 0 且不大于 1',
    ):
        BacktestRunner(
            _grid_strategy(),
            {'max_volume_participation': value},
        )


def test_volume_participation_limit_is_shared_within_bar():
    limits = _build_volume_limits({'510300': 10000}, 0.1)
    first_order = {
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 600,
    }
    second_order = {
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 500,
    }

    assert _signal_within_volume_limit(first_order, limits)
    _consume_signal_volume(first_order, limits)
    assert not _signal_within_volume_limit(second_order, limits)


def test_backtest_execution_model_prepares_slipped_volume_rejection():
    model = BacktestExecutionModel(
        slippage_rate=0.01,
        max_volume_participation=0.1,
    )
    limits = model.build_volume_limits({'510300': 5000})
    signal = {
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    }

    decision = model.prepare_order(signal, limits)

    assert not decision.accepted
    assert decision.rejection_reason == 'volume_limit'
    assert decision.signal['price'] == pytest.approx(4.04)
    assert decision.signal['amount'] == pytest.approx(4040.0)


def test_backtest_execution_model_consumes_fill_volume():
    model = BacktestExecutionModel(max_volume_participation=0.1)
    limits = model.build_volume_limits({'510300': 10000})
    first_order = {
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 600,
    }
    second_order = {
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 500,
    }

    first_decision = model.prepare_order(first_order, limits)
    assert first_decision.accepted
    model.consume_fill(first_decision.signal, limits)

    second_decision = model.prepare_order(second_order, limits)
    assert not second_decision.accepted
    assert second_decision.rejection_reason == 'volume_limit'


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


def test_trade_cost_stats_does_not_double_count_entry_commission():
    stats = _trade_cost_stats([
        {
            'action': 'buy',
            'commission': 3.0,
        },
        {
            'action': 'sell',
            'commission': 3.0,
            'entry_commission': 3.0,
        },
    ], initial_capital=10000)

    assert stats['total_commission'] == pytest.approx(6.0)
    assert stats['commission_ratio'] == pytest.approx(0.0006)


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
    assert result['total_commission'] > 0
    assert result['commission_ratio'] > 0
    assert len(result['equity_curve']) == 2
    assert '510300' not in result['portfolio']['positions']
    assert '510500' in result['portfolio']['positions']
    assert runner.strategy.selected_etfs == ['510500']
    assert len(runner.strategy.trades) == 3


def test_rotation_backtest_runner_applies_slippage_to_rebalance_orders():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
        'slippage_rate': 0.001,
    })

    result = runner.run(sample_rotation_history())

    first_buy, first_sell, second_buy = runner.executor.trades
    assert first_buy['price'] == pytest.approx(12.0 * 1.001)
    assert first_sell['price'] == pytest.approx(11.0 * 0.999)
    assert second_buy['price'] == pytest.approx(12.0 * 1.001)
    assert runner.strategy.trades[0]['price'] == pytest.approx(12.0 * 1.001)
    assert runner.strategy.trades[1]['price'] == pytest.approx(11.0 * 0.999)
    assert runner.strategy.trades[2]['price'] == pytest.approx(12.0 * 1.001)
    assert result['slippage_rate'] == 0.001
    assert runner.strategy.selected_etfs == ['510500']


def test_rotation_backtest_runner_retries_after_volume_rejection():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'max_volume_participation': 0.001,
    })

    result = runner.run(sample_rotation_history())

    assert result['trade_count'] == 0
    assert result['rejected_order_count'] == 2
    assert result['rejection_reasons'] == {'volume_limit': 2}
    assert all(
        order['reason'] == 'volume_limit'
        for order in result['rejected_orders']
    )
    assert result['max_volume_participation'] == 0.001
    assert runner.strategy.pending_rebalance_count == 0
    assert runner.strategy.last_rebalance is None


def test_rotation_backtest_runner_classifies_zero_lot_as_executor_rejection():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 1000,
        'max_volume_participation': 0.1,
    })

    result = runner.run([sample_rotation_history()[0]])

    assert result['trade_count'] == 0
    assert result['rejected_order_count'] == 1
    assert result['rejection_reasons'] == {'executor_rejected': 1}
    assert result['rejected_orders'][0]['shares'] == 0


def test_rotation_backtest_runner_rejects_missing_volume_when_limit_enabled():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'max_volume_participation': 0.1,
    })
    history = sample_rotation_history()
    history[0]['symbols']['510300'].pop('volume')

    with pytest.raises(
        ValueError,
        match='rotation history 中 510300 缺少 volume 字段',
    ):
        runner.run(history)


def test_rotation_backtest_runner_rejects_later_snapshot_missing_pool_symbol():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
    })
    history = sample_rotation_history()
    history[1]['symbols'].pop('510300')

    with pytest.raises(
        ValueError,
        match='rotation history 第 2 条 2026-01-02 缺少 ETF: 510300',
    ):
        runner.run(history)


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


def test_rotation_backtest_runner_reports_drawdown_window():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run(sample_rotation_history())

    assert result['max_drawdown'] > 0
    assert result['max_drawdown_start'] == '2026-01-01'
    assert result['max_drawdown_end'] == '2026-01-02'


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
                '159915': {'close': 10.5, 'prices': [10.0, 10.0, 10.5]},
            },
        }])


def test_rotation_backtest_runner_rejects_non_chronological_snapshots():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })
    history = list(reversed(sample_rotation_history()))

    with pytest.raises(ValueError, match='history 日期必须严格递增'):
        runner.run(history)


def test_rotation_backtest_runner_accepts_chronological_intraday_snapshots():
    runner = RotationBacktestRunner(_rotation_strategy(), {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })
    history = sample_rotation_history()
    history[0]['timestamp'] = '2026-01-01T09:30:00'
    history[0].pop('date')
    history[1]['timestamp'] = '2026-01-01T10:00:00'
    history[1].pop('date')

    result = runner.run(history)

    assert result['start_date'] == '2026-01-01T09:30:00'
    assert result['end_date'] == '2026-01-01T10:00:00'


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


def test_backtest_runner_resets_rejected_orders_between_runs():
    runner = BacktestRunner(_grid_strategy(), {
        'initial_capital': 100000,
        'max_volume_participation': 0.1,
    })
    rejected_bar = dict(sample_grid_history()[1], volume=5000)
    accepted_bar = dict(sample_grid_history()[1], volume=10000)

    first_result = runner.run([rejected_bar])
    second_result = runner.run([accepted_bar])

    assert first_result['rejected_order_count'] == 1
    assert second_result['rejected_order_count'] == 0
    assert second_result['rejection_reasons'] == {}
    assert second_result['rejected_orders'] == []


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
    assert result['max_drawdown_start'] == '2026-01-01'
    assert result['max_drawdown_end'] == '2026-01-01'


def test_backtest_runner_reports_drawdown_window_from_peak_to_trough():
    strategy = GridStrategy({
        'name': '测试回撤区间',
        'symbol': '510300',
        'center_price': 10.00,
        'grid_size': 1.00,
        'grid_count': 1,
        'shares_per_grid': 1000,
        'max_grids': 1,
    })
    runner = BacktestRunner(strategy, {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    })

    result = runner.run([
        {
            'date': '2026-01-01',
            'open': 9.00,
            'high': 9.00,
            'low': 9.00,
            'close': 9.00,
            'volume': 1000000,
            'amount': 9000000,
        },
        {
            'date': '2026-01-02',
            'open': 10.50,
            'high': 10.50,
            'low': 10.50,
            'close': 10.50,
            'volume': 1000000,
            'amount': 10500000,
        },
        {
            'date': '2026-01-03',
            'open': 8.00,
            'high': 8.00,
            'low': 8.00,
            'close': 8.00,
            'volume': 1000000,
            'amount': 8000000,
        },
    ])

    assert result['trade_count'] == 1
    assert result['max_drawdown'] > 0
    assert result['max_drawdown_start'] == '2026-01-02'
    assert result['max_drawdown_end'] == '2026-01-03'


def test_drawdown_stats_uses_latest_repeated_peak_before_trough():
    stats = _drawdown_stats([
        {'date': '2026-01-01', 'total_value': 100000},
        {'date': '2026-01-02', 'total_value': 90000},
        {'date': '2026-01-03', 'total_value': 100000},
        {'date': '2026-01-04', 'total_value': 80000},
    ], initial_capital=100000)

    assert stats['max_drawdown'] == pytest.approx(0.2)
    assert stats['max_drawdown_start'] == '2026-01-03'
    assert stats['max_drawdown_end'] == '2026-01-04'


def test_backtest_runner_rejects_empty_history():
    runner = BacktestRunner(_grid_strategy())

    with pytest.raises(ValueError, match='history 不能为空'):
        runner.run([])


def test_backtest_runner_rejects_non_positive_initial_capital():
    runner = BacktestRunner(_grid_strategy(), {'initial_capital': 0})

    with pytest.raises(ValueError, match='initial_capital 必须大于 0'):
        runner.run(sample_grid_history())


def test_backtest_runner_rejects_non_chronological_history():
    runner = BacktestRunner(_grid_strategy())
    history = list(reversed(sample_grid_history()))

    with pytest.raises(ValueError, match='history 日期必须严格递增') as exc:
        runner.run(history)

    assert '第 2 条 2026-01-02' in str(exc.value)
    assert '第 1 条 2026-01-03' in str(exc.value)


def test_backtest_runner_rejects_duplicate_history_dates():
    runner = BacktestRunner(_grid_strategy())
    history = [
        sample_grid_history()[0],
        dict(sample_grid_history()[0]),
    ]

    with pytest.raises(ValueError, match='history 日期必须严格递增'):
        runner.run(history)


def test_backtest_runner_accepts_chronological_intraday_history():
    runner = BacktestRunner(_grid_strategy())
    history = [
        {
            'timestamp': '2026-01-01T09:30:00',
            'open': 4.0,
            'high': 4.0,
            'low': 4.0,
            'close': 4.0,
        },
        {
            'timestamp': '2026-01-01T10:00:00',
            'open': 4.0,
            'high': 4.0,
            'low': 4.0,
            'close': 4.0,
        },
    ]

    result = runner.run(history)

    assert result['start_date'] == '2026-01-01T09:30:00'
    assert result['end_date'] == '2026-01-01T10:00:00'


def test_backtest_runner_rejects_weekend_with_strict_trading_calendar():
    runner = BacktestRunner(
        _grid_strategy(),
        trading_calendar=TradingCalendar(),
    )

    with pytest.raises(
        ValueError,
        match='history 第 3 条日期 2026-01-03 不是交易日',
    ):
        runner.run(sample_grid_history())


def test_rotation_backtest_runner_rejects_configured_holiday():
    runner = RotationBacktestRunner(
        _rotation_strategy(),
        trading_calendar=TradingCalendar(holidays=['2026-01-02']),
    )

    with pytest.raises(
        ValueError,
        match='history 第 2 条日期 2026-01-02 不是交易日',
    ):
        runner.run(sample_rotation_history())


def test_backtest_runner_accepts_price_only_history():
    runner = BacktestRunner(_grid_strategy())

    result = runner.run([{
        'date': '2026-01-01',
        'price': 4.0,
    }])

    assert result['start_date'] == '2026-01-01'
    assert result['final_value'] == result['initial_capital']


def test_backtest_runner_rejects_non_positive_price():
    runner = BacktestRunner(_grid_strategy())
    bar = dict(sample_grid_history()[0], close=0)

    with pytest.raises(
        ValueError,
        match='history 第 1 条字段 close/price 必须大于 0',
    ):
        runner.run([bar])


@pytest.mark.parametrize(
    ('field', 'value', 'label'),
    [
        ('close', math.nan, 'close/price'),
        ('high', math.inf, 'high'),
    ],
)
def test_backtest_runner_rejects_non_finite_prices(field, value, label):
    runner = BacktestRunner(_grid_strategy())
    bar = dict(sample_grid_history()[0], **{field: value})

    with pytest.raises(
        ValueError,
        match=f'history 第 1 条字段 {label} 必须是有限数字',
    ):
        runner.run([bar])


def test_backtest_runner_rejects_high_below_low():
    runner = BacktestRunner(_grid_strategy())
    bar = dict(
        sample_grid_history()[0],
        open=3.95,
        high=3.9,
        low=4.0,
        close=3.95,
    )

    with pytest.raises(ValueError, match='history 第 1 条 high 不能小于 low'):
        runner.run([bar])


def test_backtest_runner_rejects_close_outside_bar_range():
    runner = BacktestRunner(_grid_strategy())
    bar = dict(sample_grid_history()[0], close=4.1)

    with pytest.raises(
        ValueError,
        match='history 第 1 条 close/price 必须在 low 和 high 之间',
    ):
        runner.run([bar])


def test_backtest_runner_rejects_open_outside_bar_range():
    runner = BacktestRunner(_grid_strategy())
    bar = dict(sample_grid_history()[0], open=4.1)

    with pytest.raises(
        ValueError,
        match='history 第 1 条 open 必须在 low 和 high 之间',
    ):
        runner.run([bar])


def test_backtest_runner_rejects_negative_volume():
    runner = BacktestRunner(_grid_strategy())
    bar = dict(sample_grid_history()[0], volume=-1)

    with pytest.raises(
        ValueError,
        match='history 第 1 条字段 volume 不能小于 0',
    ):
        runner.run([bar])


def test_backtest_runner_rejects_negative_amount():
    runner = BacktestRunner(_grid_strategy())
    bar = dict(sample_grid_history()[0], amount=-1)

    with pytest.raises(
        ValueError,
        match='history 第 1 条字段 amount 不能小于 0',
    ):
        runner.run([bar])


def test_backtest_runner_rejects_invalid_slippage_rate():
    with pytest.raises(ValueError, match='slippage_rate 必须在 0 到 1 之间'):
        BacktestRunner(_grid_strategy(), {'slippage_rate': 1})


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


def test_filter_history_by_date_rejects_non_chronological_filtered_rows():
    history = list(reversed(sample_grid_history()))

    with pytest.raises(ValueError, match='history 日期必须严格递增'):
        filter_history_by_date(history)


def test_filter_history_by_date_keeps_chronological_intraday_rows():
    history = [
        {'timestamp': '2026-01-01T09:30:00'},
        {'timestamp': '2026-01-01T10:00:00'},
    ]

    filtered = filter_history_by_date(
        history,
        start_date='2026-01-01',
        end_date='2026-01-01',
    )

    assert filtered == history


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


def test_load_rotation_history_json_reads_snapshot_array(tmp_path):
    history_file = tmp_path / 'rotation-history.json'
    history_file.write_text(json.dumps([
        {
            'date': '2026-01-01',
            'symbols': {
                '510300': {
                    'close': 12.0,
                    'prices': [10.0, 11.0, 12.0],
                    'volume': 1000000,
                },
                '510500': {
                    'price': 9.0,
                    'prices': [10.0, 9.5, 9.0],
                },
            },
        },
    ]), encoding='utf-8')

    rows = load_rotation_history_json(str(history_file))

    assert rows == [{
        'date': '2026-01-01',
        'symbols': {
            '510300': {
                'close': 12.0,
                'prices': [10.0, 11.0, 12.0],
                'volume': 1000000,
            },
            '510500': {
                'close': 9.0,
                'prices': [10.0, 9.5, 9.0],
            },
        },
    }]


def test_load_rotation_history_json_rejects_missing_prices(tmp_path):
    history_file = tmp_path / 'rotation-history.json'
    history_file.write_text(json.dumps([
        {
            'date': '2026-01-01',
            'symbols': {
                '510300': {'close': 12.0},
            },
        },
    ]), encoding='utf-8')

    with pytest.raises(
        ValueError,
        match='轮动历史 JSON 第 1 条 510300 prices 必须是非空数组',
    ):
        load_rotation_history_json(str(history_file))


def test_load_rotation_history_csv_reads_long_table(tmp_path):
    history_file = tmp_path / 'rotation-history.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume\n'
        '2026-01-01,510300,12.0,10|11|12,1000000\n'
        '2026-01-01,510500,9.0,10|9.5|9,900000\n'
        '2026-01-02,510300,11.0,11|12|11,1100000\n'
        '2026-01-02,510500,12.0,9|10|12,1200000\n',
        encoding='utf-8',
    )

    rows = load_rotation_history_csv(str(history_file))

    assert rows == [
        {
            'date': '2026-01-01',
            'symbols': {
                '510300': {
                    'close': 12.0,
                    'prices': [10.0, 11.0, 12.0],
                    'volume': 1000000.0,
                },
                '510500': {
                    'close': 9.0,
                    'prices': [10.0, 9.5, 9.0],
                    'volume': 900000.0,
                },
            },
        },
        {
            'date': '2026-01-02',
            'symbols': {
                '510300': {
                    'close': 11.0,
                    'prices': [11.0, 12.0, 11.0],
                    'volume': 1100000.0,
                },
                '510500': {
                    'close': 12.0,
                    'prices': [9.0, 10.0, 12.0],
                    'volume': 1200000.0,
                },
            },
        },
    ]


def test_load_rotation_history_csv_rejects_duplicate_symbol_per_date(tmp_path):
    history_file = tmp_path / 'rotation-history.csv'
    history_file.write_text(
        'date,symbol,close,prices\n'
        '2026-01-01,510300,12.0,10|11|12\n'
        '2026-01-01,510300,11.0,10|11|11\n',
        encoding='utf-8',
    )

    with pytest.raises(
        ValueError,
        match='轮动历史 CSV 第 3 行重复标的: 2026-01-01 510300',
    ):
        load_rotation_history_csv(str(history_file))


def test_load_rotation_history_csv_rejects_duplicate_symbol_after_trim(tmp_path):
    history_file = tmp_path / 'rotation-history.csv'
    history_file.write_text(
        'date,symbol,close,prices\n'
        '2026-01-01,510300,12.0,10|11|12\n'
        '2026-01-01, 510300 ,11.0,10|11|11\n',
        encoding='utf-8',
    )

    with pytest.raises(
        ValueError,
        match='轮动历史 CSV 第 3 行重复标的: 2026-01-01 510300',
    ):
        load_rotation_history_csv(str(history_file))


def test_load_rotation_history_csv_rejects_prices_with_empty_segment(tmp_path):
    history_file = tmp_path / 'rotation-history.csv'
    history_file.write_text(
        'date,symbol,close,prices\n'
        '2026-01-01,510300,12.0,10||12\n',
        encoding='utf-8',
    )

    with pytest.raises(
        ValueError,
        match='轮动历史 CSV 第 2 行字段 prices 第 2 项不能为空',
    ):
        load_rotation_history_csv(str(history_file))


def test_write_equity_curve_csv_writes_header_and_rows(tmp_path):
    output_file = tmp_path / 'nested' / 'equity.csv'

    written_path = write_equity_curve_csv(str(output_file), [
        {
            'date': '2026-01-01',
            'total_value': 100000.0,
            'pnl': 0.0,
            'pnl_percent': 0.0,
            'period_return': 0.0,
            'drawdown': 0.0,
        },
        {
            'date': '2026-01-02',
            'total_value': 100500.5,
            'pnl': 500.5,
            'pnl_percent': 0.5005,
            'period_return': 0.005005,
            'drawdown': 0.0,
        },
    ])

    assert written_path == output_file
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert rows == [
        {
            'date': '2026-01-01',
            'total_value': '100000.0',
            'pnl': '0.0',
            'pnl_percent': '0.0',
            'period_return': '0.0',
            'drawdown': '0.0',
        },
        {
            'date': '2026-01-02',
            'total_value': '100500.5',
            'pnl': '500.5',
            'pnl_percent': '0.5005',
            'period_return': '0.005005',
            'drawdown': '0.0',
        },
    ]


def test_write_trades_csv_writes_optional_sell_fields(tmp_path):
    output_file = tmp_path / 'nested' / 'trades.csv'

    written_path = write_trades_csv(str(output_file), [
        {
            'timestamp': '2026-01-01T09:30:00',
            'action': 'buy',
            'symbol': '510300',
            'price': 3.9,
            'shares': 1000,
            'amount': 3900.0,
            'commission': 1.17,
        },
        {
            'timestamp': '2026-01-02T09:30:00',
            'action': 'sell',
            'symbol': '510300',
            'price': 4.1,
            'shares': 1000,
            'amount': 4100.0,
            'commission': 1.23,
            'entry_commission': 1.17,
            'profit': 198.77,
            'net_profit': 197.6,
        },
    ])

    assert written_path == output_file
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert rows[0]['action'] == 'buy'
    assert rows[0]['entry_commission'] == ''
    assert rows[1]['action'] == 'sell'
    assert rows[1]['entry_commission'] == '1.17'
    assert rows[1]['net_profit'] == '197.6'


def test_write_positions_csv_writes_position_snapshots(tmp_path):
    output_file = tmp_path / 'nested' / 'positions.csv'

    written_path = write_positions_csv(str(output_file), [
        {
            'date': '2026-01-02',
            'symbol': '510300',
            'shares': 1000,
            'avg_price': 3.9,
            'cost': 3900.0,
            'commission': 1.17,
            'current_price': 4.0,
            'market_value': 4000.0,
            'unrealized_pnl': 100.0,
        },
    ])

    assert written_path == output_file
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert rows == [{
        'date': '2026-01-02',
        'symbol': '510300',
        'shares': '1000',
        'avg_price': '3.9',
        'cost': '3900.0',
        'commission': '1.17',
        'current_price': '4.0',
        'market_value': '4000.0',
        'unrealized_pnl': '100.0',
    }]


def test_write_rejected_orders_csv_writes_reason_fields(tmp_path):
    output_file = tmp_path / 'nested' / 'rejections.csv'

    written_path = write_rejected_orders_csv(str(output_file), [
        {
            'timestamp': '2026-01-02',
            'action': 'buy',
            'symbol': '510300',
            'price': 3.9,
            'shares': 1000,
            'amount': 3900.0,
            'reason': 'volume_limit',
            'signal_reason': '网格买入，价格3.9',
        },
        {
            'timestamp': '2026-01-03',
            'action': 'sell',
            'symbol': '510300',
            'price': 4.1,
            'shares': 0,
            'amount': 0,
            'reason': 'executor_rejected',
        },
    ])

    assert written_path == output_file
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert set(rows[0]) == {
        'timestamp',
        'action',
        'symbol',
        'price',
        'shares',
        'amount',
        'reason',
        'signal_reason',
    }
    assert rows[0]['reason'] == 'volume_limit'
    assert rows[0]['signal_reason'] == '网格买入，价格3.9'
    assert rows[1]['reason'] == 'executor_rejected'
    assert rows[1]['signal_reason'] == ''


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
    assert '- 总手续费:' in completed.stdout
    assert '- 手续费占初始资金:' in completed.stdout
    assert '- 滑点: 0.00%' in completed.stdout
    assert '- 最大回撤区间:' in completed.stdout


def test_cli_backtest_exports_equity_curve_csv(tmp_path):
    output_file = tmp_path / 'grid-equity.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--equity-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'权益曲线 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert [row['date'] for row in rows] == [
        '2026-01-01',
        '2026-01-02',
        '2026-01-03',
    ]
    assert set(rows[0]) == {
        'date',
        'total_value',
        'pnl',
        'pnl_percent',
        'period_return',
        'drawdown',
    }
    assert float(rows[0]['total_value']) == pytest.approx(100000.0)
    assert float(rows[0]['pnl']) == pytest.approx(0.0)
    assert float(rows[0]['pnl_percent']) == pytest.approx(0.0)
    assert float(rows[0]['period_return']) == pytest.approx(0.0)
    assert float(rows[0]['drawdown']) == pytest.approx(0.0)


def test_cli_backtest_exports_trades_csv(tmp_path):
    output_file = tmp_path / 'grid-trades.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--trades-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'成交明细 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert [row['action'] for row in rows] == ['buy', 'sell']
    assert [row['timestamp'] for row in rows] == [
        '2026-01-02',
        '2026-01-03',
    ]
    assert rows[0]['symbol'] == '510300'
    assert float(rows[0]['amount']) > 0
    assert float(rows[1]['net_profit']) > 0


def test_cli_backtest_exports_positions_csv(tmp_path):
    output_file = tmp_path / 'grid-positions.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--positions-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'持仓明细 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert [row['date'] for row in rows] == ['2026-01-02']
    assert rows[0]['symbol'] == '510300'
    assert rows[0]['shares'] == '1000'
    assert float(rows[0]['current_price']) == pytest.approx(3.95)
    assert float(rows[0]['market_value']) > 0


def test_cli_backtest_exports_rejected_orders_csv(tmp_path):
    output_file = tmp_path / 'grid-rejections.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--max-volume-participation',
            '0.0001',
            '--rejections-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'拒单明细 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]['timestamp'] == '2026-01-02'
    assert rows[0]['action'] == 'buy'
    assert rows[0]['symbol'] == '510300'
    assert rows[0]['reason'] == 'volume_limit'
    assert rows[0]['signal_reason'] == '网格买入，价格3.9'


def test_cli_backtest_exports_empty_rejected_orders_csv(tmp_path):
    output_file = tmp_path / 'grid-rejections.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--rejections-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'拒单明细 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        rows = list(reader)
    assert rows == []
    assert reader.fieldnames == [
        'timestamp',
        'action',
        'symbol',
        'price',
        'shares',
        'amount',
        'reason',
        'signal_reason',
    ]


def test_cli_backtest_accepts_slippage_rate():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--slippage-rate',
            '0.01',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '- 滑点: 1.00%' in completed.stdout


def test_cli_backtest_accepts_volume_participation_limit():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--max-volume-participation',
            '0.001',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '- 成交量参与率上限: 0.10%' in completed.stdout
    assert '- 拒单次数: 0' in completed.stdout
    assert '- 拒单原因: 无' in completed.stdout


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
    assert '- 总手续费:' in completed.stdout
    assert '- 手续费占初始资金:' in completed.stdout
    assert '- 滑点: 0.00%' in completed.stdout
    assert '- 最大回撤区间:' in completed.stdout


def test_cli_rotation_backtest_exports_equity_curve_csv(tmp_path):
    output_file = tmp_path / 'rotation-equity.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--equity-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'权益曲线 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert [row['date'] for row in rows] == [
        '2026-01-01',
        '2026-01-02',
    ]
    assert set(rows[0]) == {
        'date',
        'total_value',
        'pnl',
        'pnl_percent',
        'period_return',
        'drawdown',
    }
    assert float(rows[0]['total_value']) > 0
    assert float(rows[0]['pnl']) < 0
    assert float(rows[0]['period_return']) < 0
    assert float(rows[0]['drawdown']) > 0


def test_cli_rotation_backtest_exports_trades_csv(tmp_path):
    output_file = tmp_path / 'rotation-trades.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--trades-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'成交明细 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert [row['action'] for row in rows] == ['buy', 'sell', 'buy']
    assert [row['timestamp'] for row in rows] == [
        '2026-01-01',
        '2026-01-02',
        '2026-01-02',
    ]
    assert {row['symbol'] for row in rows} == {'510300', '510500'}
    assert rows[1]['entry_commission']


def test_cli_rotation_backtest_exports_positions_csv(tmp_path):
    output_file = tmp_path / 'rotation-positions.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--positions-output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'持仓明细 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert [row['date'] for row in rows] == [
        '2026-01-01',
        '2026-01-02',
    ]
    assert [row['symbol'] for row in rows] == ['510300', '510500']
    assert all(float(row['market_value']) > 0 for row in rows)


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


def test_cli_rotation_backtest_accepts_history_json(tmp_path):
    history_file = tmp_path / 'rotation-history.json'
    history_file.write_text(json.dumps(sample_rotation_history()), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--history',
            str(history_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - 轮动回测' in completed.stdout
    assert '- 标的池: 510300,510500,159915' in completed.stdout


def test_cli_rotation_backtest_accepts_history_csv(tmp_path):
    history_file = tmp_path / 'rotation-history.csv'
    history_file.write_text(
        'date,symbol,close,prices,volume\n'
        '2026-01-01,510300,12.0,10|11|12,1000000\n'
        '2026-01-01,510500,9.0,10|9.5|9,1000000\n'
        '2026-01-01,159915,10.5,10|10|10.5,1000000\n'
        '2026-01-02,510300,11.0,11|12|11,1000000\n'
        '2026-01-02,510500,12.0,9|10|12,1000000\n'
        '2026-01-02,159915,10.2,10|10.5|10.2,1000000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'rotation',
            '--history',
            str(history_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '# 回测报告 - 轮动回测' in completed.stdout
    assert '- 标的池: 510300,510500,159915' in completed.stdout


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


def test_cli_backtest_rejects_non_chronological_csv(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n'
        '2026-01-02,4.0,4.1,3.9,4.0,1000,4000\n'
        '2026-01-01,4.0,4.1,3.9,4.0,1000,4000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--history',
            str(history_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert 'history 日期必须严格递增' in completed.stderr


def test_cli_backtest_rejects_invalid_ohlc_csv(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n'
        '2026-01-01,4.0,3.9,4.0,4.0,1000,4000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--history',
            str(history_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert 'history 第 1 条 high 不能小于 low' in completed.stderr


def test_cli_backtest_rejects_weekend_in_strict_calendar_mode(tmp_path):
    history_file = tmp_path / 'history.csv'
    history_file.write_text(
        'date,open,high,low,close,volume,amount\n'
        '2026-01-03,4.0,4.1,3.9,4.0,1000,4000\n',
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--history',
            str(history_file),
            '--strict-trading-calendar',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert 'history 第 1 条日期 2026-01-03 不是交易日' in completed.stderr


def test_cli_backtest_allows_explicit_weekend_trading_day():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--strict-trading-calendar',
            '--trading-day',
            '2026-01-03',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert '# 回测报告 - 网格回测' in completed.stdout


def test_cli_backtest_requires_strict_mode_for_calendar_overrides():
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--holiday',
            '2026-01-02',
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert '--holiday/--trading-day 需要同时启用' in completed.stderr


@pytest.mark.parametrize('value', ['20260102', '2026-W01-5'])
def test_cli_backtest_rejects_non_standard_calendar_date(value):
    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'backtest',
            '--strategy',
            'grid',
            '--strict-trading-calendar',
            '--holiday',
            value,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert f'交易日历日期必须是 YYYY-MM-DD: {value}' in completed.stderr


@pytest.mark.parametrize('option,value', [
    ('--grid-size', '0'),
    ('--initial-capital', '-1'),
    ('--slippage-rate', '1'),
    ('--max-volume-participation', '0'),
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
