import pytest

from execution.simulator import Simulator


class TestSimulator:

    def setup_method(self):
        self.sim = Simulator({'initial_capital': 100000, 'commission_rate': 0.0003})

    def test_initial_portfolio(self):
        portfolio = self.sim.get_portfolio()
        assert portfolio['capital'] == 100000
        assert portfolio['position_count'] == 0
        assert portfolio['total_value'] == 100000

    def test_rejects_non_positive_initial_capital(self):
        with pytest.raises(ValueError, match='initial_capital 必须大于 0'):
            Simulator({'initial_capital': 0})

    def test_buy_round_lot(self):
        # 只能买100的整数倍
        order = {'action': 'buy', 'symbol': '510300', 'price': 4.0, 'amount': 5000}
        result = self.sim.execute_order(order)
        assert result is True
        assert '510300' in self.sim.positions
        assert self.sim.positions['510300']['shares'] == 1200  # 5000/4=1250, 取整为1200

    def test_buy_insufficient_funds(self):
        order = {'action': 'buy', 'symbol': '510300', 'price': 4.0, 'amount': 200000}
        result = self.sim.execute_order(order)
        assert result is False

    def test_minimum_commission_applies_to_each_side(self):
        sim = Simulator({
            'initial_capital': 20000,
            'buy_commission_rate': 0.001,
            'sell_commission_rate': 0.002,
            'min_commission': 5,
        })

        assert sim.execute_order({
            'action': 'buy',
            'symbol': '510300',
            'price': 10,
            'shares': 100,
        }) is True
        assert sim.execute_order({
            'action': 'sell',
            'symbol': '510300',
            'price': 11,
            'shares': 100,
        }) is True

        assert sim.trades[0]['commission'] == pytest.approx(5)
        assert sim.trades[1]['commission'] == pytest.approx(5)
        assert sim.trades[1]['entry_commission'] == pytest.approx(5)
        assert sim.trades[1]['net_profit'] == pytest.approx(90)

    def test_buy_funds_check_includes_minimum_commission(self):
        sim = Simulator({
            'initial_capital': 1000,
            'commission_rate': 0.0003,
            'min_commission': 5,
        })

        assert sim.execute_order({
            'action': 'buy',
            'symbol': '510300',
            'price': 9.96,
            'shares': 100,
        }) is False
        assert sim.capital == 1000

    def test_legacy_commission_rate_applies_to_both_sides(self):
        sim = Simulator({
            'initial_capital': 20000,
            'commission_rate': 0.001,
            'buy_commission_rate': None,
            'sell_commission_rate': None,
        })

        assert sim.buy_commission_rate == pytest.approx(0.001)
        assert sim.sell_commission_rate == pytest.approx(0.001)

    @pytest.mark.parametrize(
        ('config', 'message'),
        [
            ({'buy_commission_rate': -0.1}, 'buy_commission_rate'),
            ({'sell_commission_rate': 1.1}, 'sell_commission_rate'),
            ({'min_commission': float('nan')}, 'min_commission'),
        ],
    )
    def test_rejects_invalid_cost_config(self, config, message):
        with pytest.raises(ValueError, match=message):
            Simulator({'initial_capital': 100000, **config})

    def test_buy_avg_price(self):
        # 第一次买入
        self.sim.execute_order({'action': 'buy', 'symbol': '510300', 'price': 4.0, 'amount': 40000})
        # 第二次买入
        self.sim.execute_order({'action': 'buy', 'symbol': '510300', 'price': 4.2, 'amount': 42000})
        pos = self.sim.positions['510300']
        # 验证均价计算正确
        expected_avg = (10000 * 4.0 + 10000 * 4.2) / 20000
        assert abs(pos['avg_price'] - expected_avg) < 0.01

    def test_sell_partial(self):
        # 买入10000股
        self.sim.execute_order({'action': 'buy', 'symbol': '510300', 'price': 4.0, 'amount': 40000})
        # 卖出5000股
        self.sim.execute_order({'action': 'sell', 'symbol': '510300', 'price': 4.2, 'amount': 21000})
        pos = self.sim.positions['510300']
        assert pos['shares'] == 5000
        # 均价应该不变
        assert abs(pos['avg_price'] - 4.0) < 0.01

    def test_sell_all(self):
        self.sim.execute_order({'action': 'buy', 'symbol': '510300', 'price': 4.0, 'amount': 40000})
        self.sim.execute_order({'action': 'sell', 'symbol': '510300', 'price': 4.2, 'amount': 42000})
        assert '510300' not in self.sim.positions

    def test_sell_trade_net_profit_includes_entry_commission(self):
        sim = Simulator({'initial_capital': 20000, 'commission_rate': 0.0003})
        assert sim.execute_order({
            'action': 'buy',
            'symbol': '510300',
            'price': 100,
            'shares': 100,
        }) is True

        assert sim.execute_order({
            'action': 'sell',
            'symbol': '510300',
            'price': 100.04,
            'shares': 100,
        }) is True

        sell_trade = sim.trades[-1]
        assert sell_trade['profit'] > 0
        assert sell_trade['entry_commission'] == pytest.approx(3.0)
        assert sell_trade['net_profit'] < 0
        assert sim.get_portfolio()['realized_pnl'] == pytest.approx(
            sell_trade['net_profit']
        )

    def test_sell_no_position(self):
        result = self.sim.execute_order({'action': 'sell', 'symbol': '510300', 'price': 4.0, 'amount': 40000})
        assert result is False

    def test_portfolio_mark_to_market(self):
        self.sim.execute_order({'action': 'buy', 'symbol': '510300', 'price': 4.0, 'amount': 40000})
        portfolio = self.sim.get_portfolio({'510300': 4.5})
        # 市值 = 10000 * 4.5 = 45000
        # 总资产 = 剩余资金 + 市值
        assert portfolio['positions']['510300']['market_value'] == 45000
        assert portfolio['positions']['510300']['unrealized_pnl'] > 0
