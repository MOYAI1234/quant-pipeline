import logging
from copy import deepcopy

from .base import BaseStrategy


logger = logging.getLogger('quant_pipeline.strategy.grid')


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
        self.grid_ledger = {}  # {grid_price: {'bought': bool, 'sold': bool}}
        self.calc_grids()
        self._init_ledger()

    def calc_grids(self):
        for i in range(1, self.grid_count + 1):
            self.buy_grids.append(self.center_price - i * self.grid_size)
            self.sell_grids.append(self.center_price + i * self.grid_size)
        self.buy_grids.sort(reverse=True)
        self.sell_grids.sort()

    def _init_ledger(self):
        for grid_price in self.buy_grids:
            self.grid_ledger[grid_price] = {'bought': False, 'sold': False}

    def on_trade_confirmed(self, trade: dict):
        """交易确认后更新 grid ledger"""
        action = trade.get('action')
        price = trade.get('price', 0)

        if action == 'buy':
            # 找到对应的网格价格
            for grid_price in self.buy_grids:
                upper_bound = grid_price + self.grid_size
                if grid_price <= price < upper_bound:
                    self.grid_ledger[grid_price]['bought'] = True
                    break
        elif action == 'sell':
            # 找到对应的网格价格并重置状态（允许再次买入）
            for grid_price in self.buy_grids:
                if self.grid_ledger[grid_price]['bought'] and not self.grid_ledger[grid_price]['sold']:
                    self.grid_ledger[grid_price] = {'bought': False, 'sold': False}
                    break

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        current_price = data.get('price', 0)
        if current_price <= 0:
            return []

        signals = []
        current_shares = self.get_current_shares(portfolio)
        current_grids = current_shares // self.shares_per_grid

        # 检查买入信号：找到未买入的网格
        if current_grids < self.max_grids:
            for buy_price in self.buy_grids:
                if self.grid_ledger[buy_price]['bought']:
                    continue
                upper_bound = buy_price + self.grid_size
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

        # 检查卖出信号：找已买入未卖出的网格
        if current_shares >= self.shares_per_grid:
            for sell_price in self.sell_grids:
                if current_price >= sell_price:
                    # 找对应的买入网格
                    for buy_price in self.buy_grids:
                        if self.grid_ledger[buy_price]['bought'] and not self.grid_ledger[buy_price]['sold']:
                            signals.append({
                                'action': 'sell',
                                'symbol': self.symbol,
                                'price': sell_price,
                                'shares': self.shares_per_grid,
                                'amount': self.shares_per_grid * sell_price,
                                'reason': f'网格卖出，价格{sell_price}'
                            })
                            break
                    break

        return signals

    def calc_position_size(self, capital: float, price: float) -> int:
        return self.shares_per_grid

    def snapshot(self) -> dict:
        return {
            'version': 1,
            'type': 'GridStrategy',
            'name': self.name,
            'symbol': self.symbol,
            'config': deepcopy(self.config),
            'grid_ledger': {
                str(price): dict(state)
                for price, state in self.grid_ledger.items()
            },
            'trades': self._serialize_trades(),
        }

    def restore(self, snapshot: dict):
        if snapshot.get('version') != 1:
            raise ValueError('不支持的 GridStrategy 状态版本')
        ledger = snapshot.get('grid_ledger', {})
        snapshot_grid_prices = self._snapshot_grid_prices(ledger)
        orphan_grid_prices = snapshot_grid_prices - set(self.buy_grids)
        if orphan_grid_prices:
            logger.warning(
                '快照中存在 %s 个已失效的网格: %s',
                len(orphan_grid_prices),
                sorted(orphan_grid_prices),
            )
        restored_ledger = {}
        for grid_price in self.buy_grids:
            restored_ledger[grid_price] = dict(
                ledger.get(str(grid_price), {'bought': False, 'sold': False})
            )
        self.grid_ledger = restored_ledger
        self._restore_trades(snapshot.get('trades', []))

    def _snapshot_grid_prices(self, ledger: dict) -> set:
        grid_prices = set()
        for price in ledger.keys():
            try:
                grid_prices.add(float(price))
            except (TypeError, ValueError):
                logger.warning('快照中存在无法识别的网格价格: %s', price)
        return grid_prices
