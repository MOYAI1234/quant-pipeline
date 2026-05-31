from .base import BaseStrategy


class GridStrategy(BaseStrategy):

    def __init__(self, config):
        super().__init__(config)
        self.center_price = config['center_price']
        self.grid_size = config['grid_size']
        self.grid_count = config['grid_count']
        self.shares_per_grid = config.get('shares_per_grid', 1000)
        self.max_grids = config.get('max_grids', self.grid_count)
        self.buy_grids = []
        self.sell_grids = []
        self.bought_grids = set()
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
        current_grids = current_shares // self.shares_per_grid

        # 检查买入信号：找到最接近当前价且价格在网格区间内的未买入网格
        if current_grids < self.max_grids:
            for i, buy_price in enumerate(self.buy_grids):
                if buy_price in self.bought_grids:
                    continue
                # 计算这个网格的上限（下一个更高网格的价格）
                upper_bound = buy_price + self.grid_size
                if buy_price < current_price <= upper_bound:
                    signals.append({
                        'action': 'buy',
                        'symbol': self.symbol,
                        'price': buy_price,
                        'shares': self.shares_per_grid,
                        'reason': f'网格买入，价格{buy_price}'
                    })
                    self.bought_grids.add(buy_price)
                    break

        # 检查卖出信号：有持仓时，找最近的卖出网格
        if current_shares >= self.shares_per_grid:
            for sell_price in self.sell_grids:
                if current_price >= sell_price:
                    signals.append({
                        'action': 'sell',
                        'symbol': self.symbol,
                        'price': sell_price,
                        'shares': self.shares_per_grid,
                        'reason': f'网格卖出，价格{sell_price}'
                    })
                    # 找回对应的买入网格并清除
                    for buy_price in self.buy_grids:
                        if buy_price in self.bought_grids:
                            self.bought_grids.discard(buy_price)
                            break
                    break

        return signals

    def calc_position_size(self, capital: float, price: float) -> int:
        return self.shares_per_grid
