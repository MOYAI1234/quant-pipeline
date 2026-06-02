from datetime import datetime

import pytest

from execution.simulator import Simulator
from persistence.state_store import JsonStateStore
from strategy.grid_strategy import GridStrategy
from strategy.rotation_strategy import RotationStrategy


def _grid_strategy():
    return GridStrategy({
        'name': '网格状态',
        'symbol': '510300',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })


def _rotation_strategy():
    return RotationStrategy({
        'name': '轮动状态',
        'symbol': '510300',
        'etf_pool': ['510300', '510500'],
        'lookback': 3,
        'top_n': 1,
        'rebalance_days': 10,
    })


def test_simulator_snapshot_round_trips_positions_and_trades():
    simulator = Simulator({'initial_capital': 100000, 'commission_rate': 0.0003})
    assert simulator.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    }) is True

    restored = Simulator({'initial_capital': 1})
    restored.restore(simulator.snapshot())

    assert restored.initial_capital == 100000
    assert restored.capital == simulator.capital
    assert restored.positions == simulator.positions
    assert restored.trades[0]['symbol'] == '510300'
    assert isinstance(restored.trades[0]['timestamp'], datetime)


def test_simulator_snapshot_positions_are_independent_copy():
    simulator = Simulator({'initial_capital': 100000})
    assert simulator.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    }) is True

    snapshot = simulator.snapshot()
    snapshot['positions']['510300']['shares'] = 0

    assert simulator.positions['510300']['shares'] == 1000


def test_grid_strategy_snapshot_round_trips_ledger_and_trades():
    strategy = _grid_strategy()
    trade = {
        'action': 'buy',
        'symbol': '510300',
        'price': 3.9,
        'shares': 1000,
    }
    strategy.record_trade(trade)
    strategy.on_trade_confirmed(trade)

    restored = _grid_strategy()
    restored.restore(strategy.snapshot())

    assert restored.grid_ledger[3.9]['bought'] is True
    assert restored.trades == [trade]


def test_rotation_strategy_snapshot_round_trips_rebalance_state():
    strategy = _rotation_strategy()
    strategy.selected_etfs = ['510500']
    strategy.pending_rebalance_count = 0
    strategy.last_rebalance = datetime.fromisoformat('2026-01-20')
    strategy.record_trade({'action': 'buy', 'symbol': '510500'})

    restored = _rotation_strategy()
    restored.restore(strategy.snapshot())

    assert restored.selected_etfs == ['510500']
    assert restored.pending_rebalance_count == 0
    assert restored.last_rebalance.isoformat() == '2026-01-20T00:00:00'
    assert restored.trades == [{'action': 'buy', 'symbol': '510500'}]


def test_json_state_store_saves_and_restores_account_and_strategy_state(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    simulator = Simulator({'initial_capital': 100000, 'commission_rate': 0.0003})
    assert simulator.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    }) is True
    strategy = _grid_strategy()
    strategy.on_trade_confirmed({
        'action': 'buy',
        'symbol': '510300',
        'price': 3.9,
        'shares': 1000,
    })

    saved = store.save(simulator, {'grid': strategy})
    restored_simulator = Simulator({'initial_capital': 1000})
    restored_strategy = _grid_strategy()
    loaded = store.restore(restored_simulator, {'grid': restored_strategy})

    assert loaded == saved
    assert restored_simulator.positions == simulator.positions
    assert restored_strategy.grid_ledger[3.9]['bought'] is True


def test_json_state_store_rejects_unknown_state_version(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    store.save_state({'version': 999})

    with pytest.raises(ValueError, match='不支持的状态文件版本'):
        store.load_state()


def test_json_state_store_rejects_unknown_explicit_state_version(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    simulator = Simulator({'initial_capital': 100000})

    with pytest.raises(ValueError, match='不支持的状态文件版本'):
        store.restore(simulator, {}, {'version': 999})
