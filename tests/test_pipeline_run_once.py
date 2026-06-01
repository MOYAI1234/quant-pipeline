import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import QuantPipeline
from strategy.grid_strategy import GridStrategy


class FakeDataManager:

    def get_etf_realtime(self, symbol):
        return {
            'symbol': symbol,
            'price': 3.95,
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


def test_run_once_executes_grid_signal_and_updates_metrics():
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
    system.data_manager = FakeDataManager()
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

