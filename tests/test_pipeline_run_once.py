from main import QuantPipeline
from strategy.grid_strategy import GridStrategy


class FakeDataManager:

    def __init__(self, prices=None):
        self.prices = prices or {'510300': 3.95}

    def get_etf_realtime(self, symbol):
        price = self.prices.get(symbol, 3.95)
        return {
            'symbol': symbol,
            'price': price,
            'open': 4.0,
            'high': 4.0,
            'low': 3.9,
            'volume': 1000000,
            'amount': 4000000,
            'size': 1000000000,
            'timestamp': '2026-06-01 10:00:00',
        }

    def get_etf_history(self, symbol, start_date, end_date):
        return []

    def connect(self):
        pass

    def disconnect(self):
        pass


def _build_system(data_manager=None, state_path=None):
    state_config = {'enabled': False}
    if state_path:
        state_config = {
            'enabled': True,
            'path': str(state_path),
            'restore_on_start': True,
            'save_on_stop': True,
        }
    system = QuantPipeline({
        'data': {},
        'account': {
            'initial_capital': 100000,
            'commission_rate': 0.0003,
        },
        'risk': {
            'max_position': 5,
            'max_single_weight': 1.0,
            'min_volume': 0,
            'min_size': 0,
            'max_premium': 1.0,
        },
        'analysis': {},
        'monitor': {
            'alert_threshold': -10,
        },
        'state': state_config,
    })
    system.data_manager = data_manager or FakeDataManager()
    return system


def _grid_strategy(symbol='510300', name='测试网格'):
    return GridStrategy({
        'name': name,
        'symbol': symbol,
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })


def test_run_once_executes_grid_signal_and_updates_metrics():
    system = _build_system()
    strategy = _grid_strategy()
    system.add_strategy(strategy)

    status = system.run_once()

    assert system.executor.positions['510300']['shares'] == 1000
    assert strategy.grid_ledger[3.9]['bought'] is True
    assert status['portfolio']['position_count'] == 1
    assert status['metrics']['position'] == 1
    assert '测试网格' in status['strategies']
    assert system.runtime_state['last_run_at']
    assert (
        system.runtime_state['last_market_time_by_symbol']['510300']
        == '2026-06-01 10:00:00'
    )
    orders = system.order_manager.get_all_orders()
    assert len(orders) == 1
    assert orders[0]['status'] == 'filled'
    assert orders[0]['symbol'] == '510300'


def test_run_once_returns_repriced_portfolio_for_existing_positions():
    system = _build_system(FakeDataManager({'510300': 4.5}))
    system.executor.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })

    status = system.run_once()

    position = status['portfolio']['positions']['510300']
    assert position['current_price'] == 4.5
    assert position['market_value'] == 4500
    assert status['portfolio']['total_value'] == status['metrics']['total_value']


def test_run_once_stop_loss_confirms_only_matching_strategy():
    system = _build_system(FakeDataManager({
        '510300': 3.8,
        '510500': 4.0,
    }))
    strategy_300 = _grid_strategy('510300', '沪深网格')
    strategy_500 = _grid_strategy('510500', '中证网格')
    system.add_strategy(strategy_300)
    system.add_strategy(strategy_500)
    system.executor.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })
    system.executor.execute_order({
        'action': 'buy',
        'symbol': '510500',
        'price': 4.0,
        'shares': 1000,
    })
    strategy_300.on_trade_confirmed({
        'action': 'buy',
        'symbol': '510300',
        'price': 3.9,
        'shares': 1000,
    })
    strategy_500.on_trade_confirmed({
        'action': 'buy',
        'symbol': '510500',
        'price': 3.9,
        'shares': 1000,
    })

    system.run_once()

    assert strategy_300.grid_ledger[3.9]['bought'] is False
    assert strategy_500.grid_ledger[3.9]['bought'] is True


def test_run_once_does_not_record_market_time_for_invalid_quote():
    system = _build_system(FakeDataManager({'510300': 0}))
    system.add_strategy(_grid_strategy())

    system.run_once()

    assert '510300' not in system.runtime_state['last_market_time_by_symbol']


def test_stop_saves_state_and_restore_state_loads_account_and_strategy(tmp_path):
    state_path = tmp_path / 'state.json'
    system = _build_system(state_path=state_path)
    strategy = _grid_strategy()
    system.add_strategy(strategy)
    system.executor.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })
    strategy.on_trade_confirmed({
        'action': 'buy',
        'symbol': '510300',
        'price': 3.9,
        'shares': 1000,
    })

    system.stop()

    restored = _build_system(state_path=state_path)
    restored_strategy = _grid_strategy()
    restored.add_strategy(restored_strategy)
    loaded_state = restored.restore_state()

    assert loaded_state
    assert restored.executor.positions['510300']['shares'] == 1000
    assert restored_strategy.grid_ledger[3.9]['bought'] is True


def test_state_persistence_round_trips_runtime_metadata(tmp_path):
    state_path = tmp_path / 'state.json'
    system = _build_system(state_path=state_path)
    system.runtime_state = {
        'last_run_at': '2026-06-03T10:00:00',
        'last_market_time_by_symbol': {
            '510300': '2026-06-03 09:30:00',
        },
    }
    system.save_state()

    restored = _build_system(state_path=state_path)
    restored.restore_state()

    assert restored.runtime_state == {
        'last_run_at': '2026-06-03T10:00:00',
        'last_market_time_by_symbol': {
            '510300': '2026-06-03 09:30:00',
        },
    }


def test_state_persistence_round_trips_order_state(tmp_path):
    state_path = tmp_path / 'state.json'
    system = _build_system(state_path=state_path)
    system.add_strategy(_grid_strategy())
    system.run_once()
    order_id = system.order_manager.get_all_orders()[0]['id']
    system.save_state()

    restored = _build_system(state_path=state_path)
    restored.restore_state()

    assert restored.order_manager.get_order(order_id)['status'] == 'filled'


def test_restore_state_skips_mismatched_strategy_state(tmp_path):
    state_path = tmp_path / 'state.json'
    system = _build_system(state_path=state_path)
    strategy = _grid_strategy()
    system.add_strategy(strategy)
    system.executor.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })
    system.save_state()

    restored = _build_system(state_path=state_path)
    restored.add_strategy(GridStrategy({
        'name': '测试网格',
        'symbol': '510500',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    }))

    assert restored.restore_state() == {}
    assert restored.executor.positions == {}


def test_stop_does_not_overwrite_state_after_restore_failure(tmp_path):
    state_path = tmp_path / 'state.json'
    system = _build_system(state_path=state_path)
    strategy = _grid_strategy()
    system.add_strategy(strategy)
    system.executor.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })
    system.save_state()
    original_state = state_path.read_text(encoding='utf-8')

    restored = _build_system(state_path=state_path)
    restored.add_strategy(GridStrategy({
        'name': '测试网格',
        'symbol': '510500',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    }))

    assert restored.restore_state() == {}
    restored.stop()

    assert state_path.read_text(encoding='utf-8') == original_state
