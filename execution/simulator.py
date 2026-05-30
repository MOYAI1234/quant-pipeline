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
        amount = order.get('amount', 0)

        if action == 'buy':
            return self._execute_buy(symbol, price, amount)
        elif action == 'sell':
            return self._execute_sell(symbol, price, amount)
        return False

    def _execute_buy(self, symbol: str, price: float, amount: float) -> bool:
        commission = amount * self.commission_rate
        total_cost = amount + commission

        if total_cost > self.capital:
            return False

        self.capital -= total_cost
        shares = int(amount / price / 100) * 100

        if symbol in self.positions:
            self.positions[symbol]['shares'] += shares
            self.positions[symbol]['cost'] += amount
        else:
            self.positions[symbol] = {
                'shares': shares,
                'cost': amount,
                'avg_price': price
            }

        self.trades.append({
            'action': 'buy',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'amount': amount,
            'commission': commission,
            'timestamp': datetime.now()
        })
        return True

    def _execute_sell(self, symbol: str, price: float, amount: float) -> bool:
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        shares = int(amount / price / 100) * 100

        if shares > position['shares']:
            shares = position['shares']

        sell_amount = shares * price
        commission = sell_amount * self.commission_rate
        net_amount = sell_amount - commission

        profit = net_amount - position['cost'] * (shares / position['shares'])

        self.capital += net_amount
        position['shares'] -= shares

        if position['shares'] <= 0:
            del self.positions[symbol]

        self.trades.append({
            'action': 'sell',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'amount': sell_amount,
            'commission': commission,
            'profit': profit,
            'timestamp': datetime.now()
        })
        return True

    def get_portfolio(self) -> dict:
        total_value = self.capital
        for symbol, pos in self.positions.items():
            total_value += pos['shares'] * pos.get('avg_price', 0)

        return {
            'capital': self.capital,
            'positions': self.positions,
            'position_count': len(self.positions),
            'total_value': total_value,
            'pnl': total_value - self.initial_capital,
            'pnl_percent': (total_value - self.initial_capital) / self.initial_capital * 100
        }
