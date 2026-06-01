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
        self.calc_grids()

    def calc_grids(self):
        for i in range(1, self.grid_count + 1):
            self.buy_grids.append(self.center_price - i * self.grid_size)
            self.sell_grids.append(self.center_price + i * self.grid_size)
        self.buy_grids.sort(reverse=True)
        self.sell_grids.sort()

    def _get_bought_grid_prices(self, portfolio: dict) -> set:
        """从 portfolio 推算已买入的网格价格"""
        if not portfolio:
            return set()
        positions = portfolio.get('positions', {})
        if self.symbol not in positions:
            return set()
        pos = positions[self.symbol]
        avg_price = pos.get('avg_price', 0)
        shares = pos.get('shares', 0)
        if shares <= 0 or avg_price <= 0:
            return set()
        # 根据均价反推已买的网格价格
        bought_prices = set()
        for grid_price in self.buy_grids:
            upper_bound = grid_price + self.grid_size
            if grid_price <= avg_price < upper_bound:
                bought_prices.add(grid_price)
                break
        return bought_prices

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        current_price = data.get('price', 0)
        if current_price <= 0:
            return []

        signals = []
        current_shares = self.get_current_shares(portfolio)
        current_grids = current_shares // self.shares_per_grid
        bought_prices = self._get_bought_grid_prices(portfolio)

        # 检查买入信号：找到最接近当前价且未买入的网格
        if current_grids < self.max_grids:
            for buy_price in self.buy_grids:
                if buy_price in bought_prices:
                    continue
                upper_bound = buy_price + self.grid_size
                # 下界包含，上界排除
                if buy_price <= current_price < upper_bound:
                    signals.append({
                        'action': 'buy',
                        'symbol': self.symbol,
                        'price': buy_price,
                        'shares': self.shares_per_grid,
                        'amount': self.shares_per_grid * buy_price,
                        'reason': f'网格买入，价格{buy_price}'
                    })
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
                        'amount': self.shares_per_grid * sell_price,
                        'reason': f'网格卖出，价格{sell_price}'
                    })
                    break

        return signals

    def calc_position_size(self, capital: float, price: float) -> int:
        return self.shares_per_grid
