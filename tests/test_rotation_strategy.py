import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.rotation_strategy import RotationStrategy


def _history(last_price, lookback=5, start_price=10.0):
    prices = [start_price] * (lookback - 1)
    prices.append(last_price)
    return prices


class TestRotationStrategy:

    def setup_method(self):
        self.strategy = RotationStrategy({
            'name': '测试轮动',
            'symbol': '510300',
            'etf_pool': ['510300', '510500', '159915'],
            'lookback': 5,
            'top_n': 2,
            'rebalance_days': 30,
        })

    def test_first_rebalance_buys_top_momentum_etfs(self):
        data = {
            '510300': {'price': 5.0, 'prices': _history(12.0)},
            '510500': {'price': 4.0, 'prices': _history(11.0)},
            '159915': {'price': 3.0, 'prices': _history(9.0)},
        }
        portfolio = {
            'capital': 10000,
            'positions': {},
            'total_value': 10000,
        }

        signals = self.strategy.generate_signal(data, portfolio)

        assert [sig['symbol'] for sig in signals] == ['510300', '510500']
        assert [sig['action'] for sig in signals] == ['buy', 'buy']
        assert signals[0]['shares'] == 1000
        assert signals[1]['shares'] == 1200
        assert self.strategy.pending_rebalance_count == 2
        assert self.strategy.last_rebalance is None

        self.strategy.on_trade_confirmed(signals[0])
        self.strategy.on_trade_confirmed(signals[1])

        assert self.strategy.pending_rebalance_count == 0
        assert self.strategy.last_rebalance is not None
        assert self.strategy.need_rebalance() is False

    def test_rebalance_sells_positions_that_drop_out_before_buying_new_selection(self):
        self.strategy.top_n = 1
        data = {
            '510300': {'price': 5.0, 'prices': _history(12.0)},
            '510500': {'price': 4.0, 'prices': _history(9.0)},
            '159915': {'price': 3.0, 'prices': _history(8.0)},
        }
        portfolio = {
            'capital': 1000,
            'positions': {
                '510500': {
                    'shares': 1000,
                    'avg_price': 4.0,
                    'current_price': 4.0,
                    'market_value': 4000,
                }
            },
            'total_value': 5000,
        }

        signals = self.strategy.generate_signal(data, portfolio)

        assert [sig['action'] for sig in signals] == ['sell', 'buy']
        assert signals[0]['symbol'] == '510500'
        assert signals[0]['shares'] == 1000
        assert signals[1]['symbol'] == '510300'
        assert signals[1]['shares'] == 1000
        assert signals[1]['amount'] == 5000
        assert self.strategy.pending_rebalance_count == 2

    def test_failed_rebalance_signal_clears_pending_and_allows_retry(self):
        data = {
            '510300': {'price': 5.0, 'prices': _history(12.0)},
            '510500': {'price': 4.0, 'prices': _history(9.0)},
            '159915': {'price': 3.0, 'prices': _history(8.0)},
        }
        portfolio = {
            'capital': 10000,
            'positions': {},
            'total_value': 10000,
        }

        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) == 2
        assert self.strategy.need_rebalance() is False

        self.strategy.on_trade_failed(signals[0])
        self.strategy.on_trade_failed(signals[1])

        assert self.strategy.pending_rebalance_count == 0
        assert self.strategy.last_rebalance is None
        assert self.strategy.need_rebalance() is True

        retry_signals = self.strategy.generate_signal(data, portfolio)
        assert len(retry_signals) == 2
        assert self.strategy.pending_rebalance_count == 2
