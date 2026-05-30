from .base import BaseStrategy


class GridStrategy(BaseStrategy):

    def __init__(self, config):
        super().__init__(config)
        self.center_price = config['center_price']
        self.grid_size = config['grid_size']
        self.grid_count = config['grid_count']
        self.capital_per_grid = config['capital_per_grid']
        self.max_position = config.get('max_position', 5)
        self.buy_grids = []
        self.sell_grids = []
        self.calc_grids()

    def calc_grids(self):
        for i in range(1, self.grid_count + 1):
            self.buy_grids.append(self.center_price - i * self.grid_size)
            self.sell_grids.append(self.center_price + i * self.grid_size)
        self.buy_grids.sort(reverse=True)
        self.sell_grids.sort()

    def generate_signal(self, data: dict) -> list:
        current_price = data.get('price', 0)
        signals = []
        for buy_price in self.buy_grids:
            if current_price <= buy_price and self.can_buy():
                signals.append({
                    'action': 'buy',
                    'price': buy_price,
                    'amount': self.capital_per_grid,
                    'reason': f'网格买入，价格{buy_price}'
                })
                break
        for sell_price in self.sell_grids:
            if current_price >= sell_price and self.can_sell():
                signals.append({
                    'action': 'sell',
                    'price': sell_price,
                    'amount': self.capital_per_grid,
                    'reason': f'网格卖出，价格{sell_price}'
                })
                break
        return signals

    def can_buy(self) -> bool:
        return self.position < self.max_position

    def can_sell(self) -> bool:
        return self.position > 0

    def calc_position_size(self, capital: float, price: float) -> int:
        amount = self.capital_per_grid
        shares = int(amount / price / 100) * 100
        return shares
