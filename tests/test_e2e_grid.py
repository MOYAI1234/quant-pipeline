import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.grid_strategy import GridStrategy
from execution.simulator import Simulator
from risk.risk_manager import RiskManager


class TestGridE2E:

    def setup_method(self):
        self.strategy = GridStrategy({
            'name': '测试网格',
            'symbol': '510300',
            'center_price': 4.00,
            'grid_size': 0.10,
            'grid_count': 3,
            'capital_per_grid': 10000,
            'max_position': 3,
        })
        self.simulator = Simulator({'initial_capital': 100000, 'commission_rate': 0.0003})
        self.risk_manager = RiskManager({
            'max_position': 3,
            'stop_loss': 0.15,
            'min_volume': 0,  # 测试时关闭流动性检查
            'min_size': 0,
        })

    def test_buy_signal_at_lower_grid(self):
        # 价格跌到买入网格
        data = {'price': 3.70, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'buy'

    def test_no_duplicate_buy(self):
        # 第一次买入
        data = {'price': 3.70, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        for sig in signals:
            risk_check = self.risk_manager.check_order(sig, portfolio)
            if risk_check['passed']:
                self.simulator.execute_order(sig)

        # 同一价格再次调用，不应再生成买入信号
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) == 0

    def test_sell_signal_with_position(self):
        # 先买入
        self.simulator.execute_order({
            'action': 'buy', 'symbol': '510300', 'price': 3.70, 'amount': 10000
        })

        # 价格涨到卖出网格
        data = {'price': 4.30, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'sell'

    def test_no_sell_without_position(self):
        # 无持仓时不应生成卖出信号
        data = {'price': 4.30, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        sell_signals = [s for s in signals if s['action'] == 'sell']
        assert len(sell_signals) == 0

    def test_full_cycle(self):
        # 完整周期：买 -> 卖 -> 盈利
        # 1. 价格下跌触发买入
        data_buy = {'price': 3.70, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_buy, portfolio)
        for sig in signals:
            risk_check = self.risk_manager.check_order(sig, portfolio)
            if risk_check['passed']:
                self.simulator.execute_order(sig)

        assert self.simulator.positions.get('510300', {}).get('shares', 0) > 0

        # 2. 价格上涨触发卖出
        data_sell = {'price': 4.30, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_sell, portfolio)
        for sig in signals:
            risk_check = self.risk_manager.check_order(sig, portfolio)
            if risk_check['passed']:
                self.simulator.execute_order(sig)

        # 3. 验证盈利
        portfolio = self.simulator.get_portfolio()
        assert portfolio['realized_pnl'] > 0