from datetime import datetime
from pathlib import Path

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


def test_simulator_snapshot_positions_deep_copy_nested_values():
    simulator = Simulator({'initial_capital': 100000})
    simulator.positions['510300'] = {
        'shares': 1000,
        'avg_price': 4.0,
        'cost': 4000,
        'meta': {'source': 'original'},
    }

    snapshot = simulator.snapshot()
    snapshot['positions']['510300']['meta']['source'] = 'changed'

    assert simulator.positions['510300']['meta']['source'] == 'original'


def test_simulator_restore_reports_missing_initial_capital():
    simulator = Simulator({'initial_capital': 100000})

    with pytest.raises(ValueError, match='缺少 initial_capital'):
        simulator.restore({'version': 1})


def test_simulator_restore_rejects_malformed_trade_snapshot():
    simulator = Simulator({'initial_capital': 100000})

    with pytest.raises(ValueError, match='成交快照缺少字段'):
        simulator.restore({
            'version': 1,
            'initial_capital': 100000,
            'trades': [{'action': 'buy'}],
        })


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


def test_grid_strategy_restore_warns_about_orphan_grid(caplog):
    strategy = _grid_strategy()

    with caplog.at_level('WARNING', logger='quant_pipeline.strategy.grid'):
        strategy.restore({
            'version': 1,
            'grid_ledger': {
                '3.9': {'bought': True, 'sold': False},
                '2.0': {'bought': True, 'sold': False},
            },
            'trades': [],
        })

    assert '已失效的网格' in caplog.text
    assert strategy.grid_ledger[3.9]['bought'] is True
    assert 2.0 not in strategy.grid_ledger


def test_rotation_strategy_snapshot_round_trips_rebalance_state():
    strategy = _rotation_strategy()
    strategy.selected_etfs = ['510500']
    strategy.pending_rebalance_count = 0
    strategy.last_rebalance = datetime.fromisoformat('2026-01-20')
    strategy.record_trade({
        'action': 'buy',
        'symbol': '510500',
        'timestamp': datetime.fromisoformat('2026-01-20T09:30:00'),
    })

    restored = _rotation_strategy()
    restored.restore(strategy.snapshot())

    assert restored.selected_etfs == ['510500']
    assert restored.pending_rebalance_count == 0
    assert restored.last_rebalance.isoformat() == '2026-01-20T00:00:00'
    assert restored.trades == [{
        'action': 'buy',
        'symbol': '510500',
        'timestamp': datetime.fromisoformat('2026-01-20T09:30:00'),
    }]


def test_json_state_store_persists_rotation_trade_timestamp(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    simulator = Simulator({'initial_capital': 100000})
    strategy = _rotation_strategy()
    strategy.record_trade({
        'action': 'buy',
        'symbol': '510500',
        'timestamp': datetime.fromisoformat('2026-01-20T09:30:00'),
    })

    store.save(simulator, {'rotation': strategy})

    restored = _rotation_strategy()
    store.restore(Simulator({'initial_capital': 100000}), {'rotation': restored})
    assert restored.trades[0]['timestamp'] == datetime.fromisoformat(
        '2026-01-20T09:30:00'
    )


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


def test_json_state_store_saves_metadata_without_mutating_source(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    simulator = Simulator({'initial_capital': 100000})
    metadata = {
        'last_run_at': '2026-06-03T10:00:00',
        'last_market_time_by_symbol': {
            '510300': '2026-06-03 09:30:00',
        },
    }

    saved = store.save(simulator, {}, metadata)
    metadata['last_market_time_by_symbol']['510300'] = 'changed'
    loaded = store.load_state()

    assert (
        saved['metadata']['last_market_time_by_symbol']['510300']
        == '2026-06-03 09:30:00'
    )
    assert (
        loaded['metadata']['last_market_time_by_symbol']['510300']
        == '2026-06-03 09:30:00'
    )


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


def test_json_state_store_rejects_strategy_type_mismatch(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    simulator = Simulator({'initial_capital': 100000})
    strategy = _grid_strategy()

    with pytest.raises(ValueError, match='策略状态类型不匹配'):
        store.restore(simulator, {'grid': strategy}, {
            'version': 1,
            'strategies': {
                'grid': {
                    'version': 1,
                    'type': 'RotationStrategy',
                },
            },
        })


def test_json_state_store_rejects_strategy_symbol_mismatch_before_account_restore(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    source_simulator = Simulator({'initial_capital': 100000})
    source_simulator.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })
    source_strategy = _grid_strategy()
    state = store.save(source_simulator, {'grid': source_strategy})

    target_simulator = Simulator({'initial_capital': 100000})
    target_strategy = GridStrategy({
        'name': '网格状态',
        'symbol': '510500',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })

    with pytest.raises(ValueError, match='策略状态标的不匹配'):
        store.restore(target_simulator, {'grid': target_strategy}, state)

    assert target_simulator.positions == {}


def test_json_state_store_rejects_strategy_config_mismatch(tmp_path):
    store = JsonStateStore(str(tmp_path / 'state.json'))
    simulator = Simulator({'initial_capital': 100000})
    strategy = _grid_strategy()
    state = store.save(simulator, {'grid': strategy})
    changed_strategy = GridStrategy({
        'name': '网格状态',
        'symbol': '510300',
        'center_price': 4.10,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })

    with pytest.raises(ValueError, match='策略状态配置不匹配'):
        store.restore(Simulator({'initial_capital': 100000}), {'grid': changed_strategy}, state)


def test_json_state_store_anchors_relative_path_to_project_root():
    store = JsonStateStore('data/state.json')

    assert store.path == Path(__file__).resolve().parent.parent / 'data' / 'state.json'
