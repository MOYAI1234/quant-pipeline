import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.grid_strategy import GridStrategy
from execution.simulator import Simulator
from risk.risk_manager import RiskManager


class TestGridE2E:

    def setup_method(self):
        # 网格: buy_grids = [3.9, 3.8, 3.7], sell_grids = [4.1, 4.2, 4.3]
        self.strategy = GridStrategy({
            'name': '测试网格',
            'symbol': '510300',
            'center_price': 4.00,
            'grid_size': 0.10,
            'grid_count': 3,
            'shares_per_grid': 1000,
            'max_grids': 3,
        })
        self.simulator = Simulator({'initial_capital': 100000, 'commission_rate': 0.0003})
        self.risk_manager = RiskManager({
            'max_position': 3,
            'stop_loss': 0.15,
            'min_volume': 0,
            'min_size': 0,
        })

    def test_buy_at_grid_39(self):
        # 价格 3.95 应触发 3.9 网格买入
        data = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'buy'
        assert signals[0]['price'] == 3.9
        assert signals[0]['shares'] == 1000

    def test_multi_level_buy(self):
        # 第一格买入 (3.9 网格)
        data = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        for sig in signals:
            self.simulator.execute_order(sig)
        assert self.simulator.positions.get('510300', {}).get('shares', 0) == 1000

        # 第二格买入 (3.8 网格)
        data = {'price': 3.85, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'buy'
        assert signals[0]['price'] == 3.8
        # 执行第二个信号
        for sig in signals:
            self.simulator.execute_order(sig)

        # 验证持仓增加到 2000
        assert self.simulator.positions.get('510300', {}).get('shares', 0) == 2000

    def test_no_duplicate_buy_same_grid(self):
        # 第一格买入 (3.9 网格)
        data = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        for sig in signals:
            self.simulator.execute_order(sig)

        # 同一网格区间再次调用，不应再生成买入信号
        data = {'price': 3.92, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) == 0

    def test_sell_full_grid(self):
        # 买入一格 (3.9 网格)
        self.simulator.execute_order({
            'action': 'buy', 'symbol': '510300', 'price': 3.9, 'shares': 1000
        })

        # 价格涨到卖出网格 (4.1)
        data = {'price': 4.15, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'sell'
        assert signals[0]['shares'] == 1000

    def test_sell_no_residual(self):
        # 买入1000股
        self.simulator.execute_order({
            'action': 'buy', 'symbol': '510300', 'price': 3.9, 'shares': 1000
        })

        # 卖出一格（1000股）
        self.simulator.execute_order({
            'action': 'sell', 'symbol': '510300', 'price': 4.1, 'shares': 1000
        })

        # 验证无残仓
        assert '510300' not in self.simulator.positions

    def test_full_cycle_profitable(self):
        # 1. 价格下跌触发买入 (3.9 网格)
        data_buy = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_buy, portfolio)
        for sig in signals:
            self.simulator.execute_order(sig)

        assert self.simulator.positions.get('510300', {}).get('shares', 0) == 1000

        # 2. 价格上涨触发卖出 (4.1 网格)
        data_sell = {'price': 4.15, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_sell, portfolio)
        for sig in signals:
            self.simulator.execute_order(sig)

        # 3. 验证盈利
        portfolio = self.simulator.get_portfolio()
        assert portfolio['realized_pnl'] > 0
        assert '510300' not in self.simulator.positions

    def test_max_grids_limit(self):
        # 买入3格（达到上限）
        for price in [3.95, 3.85, 3.75]:
            data = {'price': price, 'volume': 1000000, 'amount': 4000000}
            portfolio = self.simulator.get_portfolio()
            signals = self.strategy.generate_signal(data, portfolio)
            for sig in signals:
                self.simulator.execute_order(sig)

        # 第4格不应买入
        data = {'price': 3.65, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) == 0
