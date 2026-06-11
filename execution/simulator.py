from copy import deepcopy
from datetime import datetime
import math

from .executor import BaseExecutor


class Simulator(BaseExecutor):

    def __init__(self, config):
        super().__init__(config)
        self.initial_capital = config.get('initial_capital', 100000)
        if self.initial_capital <= 0:
            raise ValueError('initial_capital 必须大于 0')
        self.capital = self.initial_capital
        self.positions = {}
        self.trades = []
        self.commission_rate = config.get('commission_rate', 0.0003)
        self.buy_commission_rate = (
            config.get('buy_commission_rate')
            if config.get('buy_commission_rate') is not None
            else self.commission_rate
        )
        self.sell_commission_rate = (
            config.get('sell_commission_rate')
            if config.get('sell_commission_rate') is not None
            else self.commission_rate
        )
        self.min_commission = config.get('min_commission', 0.0)
        self._validate_cost_config()

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
        commission = self._commission(actual_amount, self.buy_commission_rate)
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
            pos['commission'] = pos.get('commission', 0) + commission
        else:
            self.positions[symbol] = {
                'shares': shares,
                'avg_price': price,
                'cost': actual_amount,
                'commission': commission
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
        commission = self._commission(sell_amount, self.sell_commission_rate)
        net_amount = sell_amount - commission

        cost_basis = shares_to_sell * pos['avg_price']
        profit = net_amount - cost_basis
        entry_commission = self._allocated_entry_commission(pos, shares_to_sell)
        net_profit = profit - entry_commission

        self.capital += net_amount

        pos['shares'] -= shares_to_sell
        pos['cost'] = pos['shares'] * pos['avg_price']
        pos['commission'] = max(pos.get('commission', 0) - entry_commission, 0)

        if pos['shares'] <= 0:
            del self.positions[symbol]

        self.trades.append({
            'action': 'sell',
            'symbol': symbol,
            'price': price,
            'shares': shares_to_sell,
            'amount': sell_amount,
            'commission': commission,
            'entry_commission': entry_commission,
            'profit': profit,
            'net_profit': net_profit,
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
                'commission': pos.get('commission', 0),
                'current_price': current_price,
                'market_value': market_value,
                'unrealized_pnl': unrealized_pnl
            }
            total_market_value += market_value

        realized_pnl = sum(
            self._trade_net_profit(trade)
            for trade in self.trades
            if trade.get('action') == 'sell'
        )

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

    def snapshot(self) -> dict:
        return {
            'version': 1,
            'initial_capital': self.initial_capital,
            'capital': self.capital,
            'positions': deepcopy(self.positions),
            'trades': [self._serialize_trade(trade) for trade in self.trades],
            'commission_rate': self.commission_rate,
            'buy_commission_rate': self.buy_commission_rate,
            'sell_commission_rate': self.sell_commission_rate,
            'min_commission': self.min_commission,
        }

    def restore(self, snapshot: dict):
        if snapshot.get('version') != 1:
            raise ValueError('不支持的 Simulator 状态版本')
        if 'initial_capital' not in snapshot:
            raise ValueError('Simulator 快照缺少 initial_capital 字段')
        initial_capital = snapshot.get('initial_capital')
        if initial_capital <= 0:
            raise ValueError('initial_capital 必须大于 0')

        self.initial_capital = initial_capital
        self.capital = snapshot.get('capital', initial_capital)
        self.positions = deepcopy(snapshot.get('positions', {}))
        self.trades = [
            self._deserialize_trade(trade)
            for trade in snapshot.get('trades', [])
        ]
        self.commission_rate = snapshot.get('commission_rate', self.commission_rate)
        self.buy_commission_rate = (
            snapshot.get('buy_commission_rate')
            if snapshot.get('buy_commission_rate') is not None
            else self.commission_rate
        )
        self.sell_commission_rate = (
            snapshot.get('sell_commission_rate')
            if snapshot.get('sell_commission_rate') is not None
            else self.commission_rate
        )
        self.min_commission = snapshot.get('min_commission', 0.0)
        self._validate_cost_config()

    def _serialize_trade(self, trade: dict) -> dict:
        serialized = deepcopy(trade)
        timestamp = serialized.get('timestamp')
        if isinstance(timestamp, datetime):
            serialized['timestamp'] = timestamp.isoformat()
        return serialized

    def _deserialize_trade(self, trade: dict) -> dict:
        self._validate_trade_snapshot(trade)
        restored = deepcopy(trade)
        timestamp = restored.get('timestamp')
        if isinstance(timestamp, str) and timestamp:
            restored['timestamp'] = datetime.fromisoformat(timestamp)
        return restored

    def _allocated_entry_commission(self, position: dict, shares_to_sell: int) -> float:
        position_shares = position.get('shares', 0)
        if position_shares <= 0:
            return 0
        return position.get('commission', 0) * shares_to_sell / position_shares

    def _commission(self, amount: float, rate: float) -> float:
        return max(amount * rate, self.min_commission)

    def _validate_cost_config(self) -> None:
        for name, value in (
            ('commission_rate', self.commission_rate),
            ('buy_commission_rate', self.buy_commission_rate),
            ('sell_commission_rate', self.sell_commission_rate),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or value > 1
            ):
                raise ValueError(f'{name} 必须在 0 到 1 之间')
        if (
            isinstance(self.min_commission, bool)
            or not isinstance(self.min_commission, (int, float))
            or not math.isfinite(self.min_commission)
            or self.min_commission < 0
        ):
            raise ValueError('min_commission 不能小于 0')

    def _trade_net_profit(self, trade: dict) -> float:
        if 'net_profit' in trade:
            return trade.get('net_profit', 0)
        return trade.get('profit', 0) - trade.get('entry_commission', 0)

    def _validate_trade_snapshot(self, trade: dict):
        if not isinstance(trade, dict):
            raise ValueError('Simulator 成交快照必须是 dict')
        required_fields = {'action', 'symbol', 'price', 'shares', 'amount'}
        missing_fields = required_fields - set(trade.keys())
        if missing_fields:
            raise ValueError(
                f"Simulator 成交快照缺少字段: {', '.join(sorted(missing_fields))}"
            )
