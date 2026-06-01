from datetime import datetime
from .executor import BaseExecutor


class Simulator(BaseExecutor):

    def __init__(self, config):
        super().__init__(config)
        self.initial_capital = config.get('initial_capital', 100000)
        self.capital = self.initial_capital
        self.positions = {}
        self.trades = []
        self.commission_rate = config.get('commission_rate', 0.0003)

    def execute_order(self, order: dict) -> bool:
        action = order.get('action')
        symbol = order.get('symbol', '')
        price = order.get('price', 0)
        shares = order.get('shares', 0)
        amount = order.get('amount', 0)

        if action == 'buy':
            if shares > 0:
                return self._execute_buy_by_shares(symbol, price, shares)
            return self._execute_buy(symbol, price, amount)
        elif action == 'sell':
            if shares > 0:
                return self._execute_sell_by_shares(symbol, price, shares)
            return self._execute_sell(symbol, price, amount)
        elif action == 'rebalance':
            return self._execute_rebalance(order)
        return False

    def _execute_buy_by_shares(self, symbol: str, price: float, shares: int) -> bool:
        if not symbol or not symbol.strip():
            return False
        if price <= 0 or shares <= 0:
            return False

        shares = (shares // 100) * 100
        if shares <= 0:
            return False

        actual_amount = shares * price
        commission = actual_amount * self.commission_rate
        total_cost = actual_amount + commission

        if total_cost > self.capital:
            return False

        self.capital -= total_cost

        if symbol in self.positions:
            pos = self.positions[symbol]
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

    def _execute_buy(self, symbol: str, price: float, amount: float) -> bool:
        if price <= 0:
            return False

        shares = int(amount / price / 100) * 100
        if shares <= 0:
            return False

        return self._execute_buy_by_shares(symbol, price, shares)

    def _execute_sell_by_shares(self, symbol: str, price: float, shares: int) -> bool:
        if symbol not in self.positions:
            return False

        pos = self.positions[symbol]
        if price <= 0 or pos['shares'] <= 0:
            return False

        shares_to_sell = min(shares, pos['shares'])
        shares_to_sell = (shares_to_sell // 100) * 100
        if shares_to_sell <= 0:
            return False

        sell_amount = shares_to_sell * price
        commission = sell_amount * self.commission_rate
        net_amount = sell_amount - commission

        cost_basis = shares_to_sell * pos['avg_price']
        profit = net_amount - cost_basis

        self.capital += net_amount

        pos['shares'] -= shares_to_sell
        pos['cost'] = pos['shares'] * pos['avg_price']

        if pos['shares'] <= 0:
            del self.positions[symbol]

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

    def _execute_sell(self, symbol: str, price: float, amount: float) -> bool:
        if price <= 0:
            return False
        shares = int(amount / price / 100) * 100
        return self._execute_sell_by_shares(symbol, price, shares)

    def _execute_rebalance(self, order: dict) -> bool:
        symbol = order.get('symbol', '')
        target_weight = order.get('target_weight', 0)
        reason = order.get('reason', 'rebalance')

        if not symbol or target_weight <= 0:
            return False

        current_prices = {}
        if symbol in self.positions:
            current_prices[symbol] = self.positions[symbol]['avg_price']

        portfolio = self.get_portfolio(current_prices)
        total_value = portfolio['total_value']
        target_value = total_value * target_weight
        current_value = 0

        if symbol in self.positions:
            current_value = self.positions[symbol]['shares'] * self.positions[symbol]['avg_price']

        diff = target_value - current_value
        price = order.get('price', 0)

        if price <= 0:
            if symbol in self.positions:
                price = self.positions[symbol]['avg_price']
            else:
                return False

        if diff > 0:
            shares = int(diff / price / 100) * 100
            if shares > 0:
                return self._execute_buy_by_shares(symbol, price, shares)
        elif diff < 0:
            shares = int(abs(diff) / price / 100) * 100
            if shares > 0:
                return self._execute_sell_by_shares(symbol, price, shares)

        return True

    def get_portfolio(self, current_prices: dict = None) -> dict:
        total_market_value = self.capital

        positions_with_value = {}
        for symbol, pos in self.positions.items():
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
