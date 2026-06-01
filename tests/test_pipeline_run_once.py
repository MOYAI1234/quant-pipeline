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


def _build_system(data_manager=None):
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
    })
    system.data_manager = data_manager or FakeDataManager()
    return system


def test_run_once_executes_grid_signal_and_updates_metrics():
    system = _build_system()
    strategy = GridStrategy({
        'name': '测试网格',
        'symbol': '510300',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 3,
        'shares_per_grid': 1000,
        'max_grids': 3,
    })
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
