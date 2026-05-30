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

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        current_price = data.get('price', 0)
        if current_price <= 0:
            return []

        signals = []
        current_shares = self.get_current_shares(portfolio)

        # 检查买入信号（当前无持仓或持仓未满）
        if current_shares == 0:
            for buy_price in self.buy_grids:
                if current_price <= buy_price:
                    signals.append({
                        'action': 'buy',
                        'symbol': self.symbol,
                        'price': buy_price,
                        'amount': self.capital_per_grid,
                        'reason': f'网格买入，价格{buy_price}'
                    })
                    break

        # 检查卖出信号（有持仓才能卖）
        if current_shares > 0:
            for sell_price in self.sell_grids:
                if current_price >= sell_price:
                    signals.append({
                        'action': 'sell',
                        'symbol': self.symbol,
                        'price': sell_price,
                        'amount': self.capital_per_grid,
                        'reason': f'网格卖出，价格{sell_price}'
                    })
                    break

        return signals

    def calc_position_size(self, capital: float, price: float) -> int:
        amount = self.capital_per_grid
        shares = int(amount / price / 100) * 100
        return shares
