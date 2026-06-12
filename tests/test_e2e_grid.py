import pytest

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

    def _execute_and_confirm(self, signals):
        """执行信号并确认交易"""
        for sig in signals:
            success = self.simulator.execute_order(sig)
            if success:
                self.strategy.on_trade_confirmed(sig)

    def test_buy_at_grid_39(self):
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
        self._execute_and_confirm(signals)
        assert self.simulator.positions.get('510300', {}).get('shares', 0) == 1000

        # 第二格买入 (3.8 网格)
        data = {'price': 3.85, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'buy'
        assert signals[0]['price'] == 3.8
        self._execute_and_confirm(signals)

        # 验证持仓增加到 2000
        assert self.simulator.positions.get('510300', {}).get('shares', 0) == 2000

    def test_no_duplicate_buy_same_grid(self):
        # 第一格买入 (3.9 网格)
        data = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        self._execute_and_confirm(signals)

        # 同一网格区间再次调用，不应再生成买入信号
        data = {'price': 3.92, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) == 0

    def test_partial_buy_tracks_remaining_grid_shares(self):
        self.strategy.max_grids = 1
        partial_buy = {
            'action': 'buy',
            'symbol': '510300',
            'price': 3.9,
            'shares': 500,
            'partial_fill': True,
        }
        assert self.simulator.execute_order(partial_buy) is True
        self.strategy.on_trade_confirmed(partial_buy)

        assert self.strategy.grid_ledger[3.9]['shares'] == 500
        assert self.strategy.grid_ledger[3.9]['bought'] is False

        portfolio = self.simulator.get_portfolio()
        lower_grid_signals = self.strategy.generate_signal(
            {'price': 3.85, 'volume': 1000000, 'amount': 4000000},
            portfolio,
        )
        assert lower_grid_signals == []

        signals = self.strategy.generate_signal(
            {'price': 3.95, 'volume': 1000000, 'amount': 4000000},
            portfolio,
        )

        assert len(signals) == 1
        assert signals[0]['shares'] == 500

    def test_sell_full_grid(self):
        # 买入一格 (3.9 网格)
        data = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        self._execute_and_confirm(signals)

        # 价格涨到卖出网格 (4.1)
        data = {'price': 4.15, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) > 0
        assert signals[0]['action'] == 'sell'
        assert signals[0]['shares'] == 1000

    def test_sell_no_residual(self):
        # 买入1000股
        data = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        self._execute_and_confirm(signals)

        # 卖出一格（1000股）
        sell_sig = {'action': 'sell', 'symbol': '510300', 'price': 4.1, 'shares': 1000}
        self.simulator.execute_order(sell_sig)
        self.strategy.on_trade_confirmed(sell_sig)

        # 验证无残仓
        assert '510300' not in self.simulator.positions

    def test_full_cycle_profitable(self):
        # 1. 价格下跌触发买入 (3.9 网格)
        data_buy = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_buy, portfolio)
        self._execute_and_confirm(signals)

        assert self.simulator.positions.get('510300', {}).get('shares', 0) == 1000

        # 2. 价格上涨触发卖出 (4.1 网格)
        data_sell = {'price': 4.15, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_sell, portfolio)
        self._execute_and_confirm(signals)

        # 3. 验证盈利
        portfolio = self.simulator.get_portfolio()
        assert portfolio['realized_pnl'] > 0
        assert '510300' not in self.simulator.positions

    def test_stop_loss_sell_resets_grid_ledger_and_allows_reentry(self):
        # 买入一格 (3.9 网格)
        data_buy = {'price': 3.95, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data_buy, portfolio)
        self._execute_and_confirm(signals)

        assert self.strategy.grid_ledger[3.9]['bought'] is True

        # 跌破止损后由风控清仓
        portfolio = self.simulator.get_portfolio({'510300': 3.6})
        stop_signals = self.risk_manager.check_portfolio_stop_loss(portfolio)
        assert len(stop_signals) == 1
        assert stop_signals[0]['action'] == 'sell'

        success = self.simulator.execute_order(stop_signals[0])
        assert success is True
        self.strategy.on_trade_confirmed(stop_signals[0])

        assert '510300' not in self.simulator.positions
        assert self.strategy.grid_ledger[3.9]['bought'] is False

        # 回到同一买入网格后，可以再次生成买入信号
        portfolio = self.simulator.get_portfolio()
        reentry_signals = self.strategy.generate_signal(data_buy, portfolio)
        assert len(reentry_signals) == 1
        assert reentry_signals[0]['action'] == 'buy'
        assert reentry_signals[0]['price'] == 3.9

    def test_max_grids_limit(self):
        # 买入3格（达到上限）
        for price in [3.95, 3.85, 3.75]:
            data = {'price': price, 'volume': 1000000, 'amount': 4000000}
            portfolio = self.simulator.get_portfolio()
            signals = self.strategy.generate_signal(data, portfolio)
            self._execute_and_confirm(signals)

        # 第4格不应买入
        data = {'price': 3.65, 'volume': 1000000, 'amount': 4000000}
        portfolio = self.simulator.get_portfolio()
        signals = self.strategy.generate_signal(data, portfolio)
        assert len(signals) == 0
