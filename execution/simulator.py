from datetime import datetime
from .executor import BaseExecutor


class Simulator(BaseExecutor):

    def __init__(self, config):
        super().__init__(config)
        self.initial_capital = config.get('initial_capital', 100000)
        self.capital = self.initial_capital
        self.positions = {}  # {symbol: {'shares': int, 'avg_price': float, 'cost': float}}
        self.trades = []
        self.commission_rate = config.get('commission_rate', 0.0003)

    def execute_order(self, order: dict) -> bool:
        action = order.get('action')
        symbol = order.get('symbol', '')
        price = order.get('price', 0)
        amount = order.get('amount', 0)

        if action == 'buy':
            return self._execute_buy(symbol, price, amount)
        elif action == 'sell':
            return self._execute_sell(symbol, price, amount)
        elif action == 'rebalance':
            return self._execute_rebalance(order)
        return False

    def _execute_buy(self, symbol: str, price: float, amount: float) -> bool:
        if price <= 0:
            return False

        # 计算可买股数（整手，100股为一手）
        shares = int(amount / price / 100) * 100
        if shares <= 0:
            return False

        # 计算实际成本
        actual_amount = shares * price
        commission = actual_amount * self.commission_rate
        total_cost = actual_amount + commission

        # 检查资金是否充足
        if total_cost > self.capital:
            return False

        # 扣除资金
        self.capital -= total_cost

        # 更新持仓
        if symbol in self.positions:
            pos = self.positions[symbol]
            # 加仓：重新计算均价
            old_cost = pos['shares'] * pos['avg_price']
            new_total_shares = pos['shares'] + shares
            new_avg_price = (old_cost + actual_amount) / new_total_shares
            pos['shares'] = new_total_shares
            pos['avg_price'] = new_avg_price
            pos['cost'] += actual_amount
        else:
            self.positions[symbol] = {
                'shares': shares,
                'avg_price': price,
                'cost': actual_amount
            }

        # 记录交易
        self.trades.append({
            'action': 'buy',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'amount': actual_amount,
            'commission': commission,
            'timestamp': datetime.now()
        })
        return True

    def _execute_sell(self, symbol: str, price: float, amount: float) -> bool:
        if symbol not in self.positions:
            return False

        pos = self.positions[symbol]
        if price <= 0 or pos['shares'] <= 0:
            return False

        # 计算卖出股数（整手）
        shares_to_sell = int(amount / price / 100) * 100
        if shares_to_sell <= 0:
            return False

        # 不能卖出超过持仓
        shares_to_sell = min(shares_to_sell, pos['shares'])

        # 计算卖出金额
        sell_amount = shares_to_sell * price
        commission = sell_amount * self.commission_rate
        net_amount = sell_amount - commission

        # 计算盈亏（基于均价）
        cost_basis = shares_to_sell * pos['avg_price']
        profit = net_amount - cost_basis

        # 更新资金
        self.capital += net_amount

        # 更新持仓（按比例扣减成本）
        remaining_ratio = (pos['shares'] - shares_to_sell) / pos['shares']
        pos['shares'] -= shares_to_sell
        pos['cost'] *= remaining_ratio

        # 清理空持仓
        if pos['shares'] <= 0:
            del self.positions[symbol]

        # 记录交易
        self.trades.append({
            'action': 'sell',
            'symbol': symbol,
            'price': price,
            'shares': shares_to_sell,
            'amount': sell_amount,
            'commission': commission,
            'profit': profit,
            'timestamp': datetime.now()
        })
        return True

    def _execute_rebalance(self, order: dict) -> bool:
        # 简化实现：先卖后买
        symbol = order.get('symbol', '')
        target_weight = order.get('target_weight', 0)
        # TODO: 完整实现再平衡逻辑
        return True

    def get_portfolio(self, current_prices: dict = None) -> dict:
        """获取组合状态，使用 mark-to-market 估值"""
        total_market_value = self.capital

        positions_with_value = {}
        for symbol, pos in self.positions.items():
            # 使用当前市价，如果没有则用均价
            if current_prices and symbol in current_prices:
                current_price = current_prices[symbol]
            else:
                current_price = pos['avg_price']

            market_value = pos['shares'] * current_price
            unrealized_pnl = market_value - pos['cost']

            positions_with_value[symbol] = {
                'shares': pos['shares'],
                'avg_price': pos['avg_price'],
                'cost': pos['cost'],
                'current_price': current_price,
                'market_value': market_value,
                'unrealized_pnl': unrealized_pnl
            }
            total_market_value += market_value

        # 计算已实现盈亏
        realized_pnl = sum(t.get('profit', 0) for t in self.trades if t.get('action') == 'sell')

        return {
            'capital': self.capital,
            'positions': positions_with_value,
            'position_count': len(self.positions),
            'total_value': total_market_value,
            'initial_capital': self.initial_capital,
            'pnl': total_market_value - self.initial_capital,
            'pnl_percent': (total_market_value - self.initial_capital) / self.initial_capital * 100,
            'realized_pnl': realized_pnl
        }
