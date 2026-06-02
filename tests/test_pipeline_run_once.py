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


def _grid_strategy():
    return GridStrategy({
        'name': '测试网格',
        'symbol': '510300',
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
