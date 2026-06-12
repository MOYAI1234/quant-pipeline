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
        self.grid_ledger = {}
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
            self.grid_ledger[grid_price] = {
                'bought': False,
                'sold': False,
                'shares': 0,
            }

    def on_trade_confirmed(self, trade: dict):
        """交易确认后更新 grid ledger"""
        action = trade.get('action')
        price = trade.get('price', 0)
        signal_price = trade.get('signal_price', price)
        trade_shares = self._trade_shares(trade)

        if action == 'buy':
            for grid_price in self.buy_grids:
                upper_bound = grid_price + self.grid_size
                if grid_price <= signal_price < upper_bound:
                    state = self.grid_ledger[grid_price]
                    state['shares'] = min(
                        state.get('shares', 0) + trade_shares,
                        self.shares_per_grid,
                    )
                    state['bought'] = state['shares'] >= self.shares_per_grid
                    state['sold'] = False
                    break
        elif action == 'sell':
            remaining_shares = trade_shares
            for grid_price in self.buy_grids:
                state = self.grid_ledger[grid_price]
                grid_shares = state.get('shares', 0)
                if grid_shares <= 0:
                    continue
                sold_shares = min(grid_shares, remaining_shares)
                state['shares'] = grid_shares - sold_shares
                state['bought'] = state['shares'] >= self.shares_per_grid
                state['sold'] = False
                remaining_shares -= sold_shares
                if remaining_shares <= 0:
                    break

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        current_price = data.get('price', 0)
        if current_price <= 0:
            return []

        signals = []
        current_shares = self.get_current_shares(portfolio)
        ledger_grids = sum(
            1
            for state in self.grid_ledger.values()
            if state.get('shares', 0) > 0
        )
        position_grids = (
            (current_shares + self.shares_per_grid - 1)
            // self.shares_per_grid
        )
        occupied_grids = max(ledger_grids, position_grids)

        # 检查买入信号：找到未买入的网格
        if occupied_grids <= self.max_grids:
            for buy_price in self.buy_grids:
                state = self.grid_ledger[buy_price]
                if state['bought']:
                    continue
                if (
                    state.get('shares', 0) <= 0
                    and occupied_grids >= self.max_grids
                ):
                    continue
                remaining_shares = (
                    self.shares_per_grid
                    - state.get('shares', 0)
                )
                if remaining_shares <= 0:
                    continue
                upper_bound = buy_price + self.grid_size
                if buy_price <= current_price < upper_bound:
                    signals.append({
                        'action': 'buy',
                        'symbol': self.symbol,
                        'price': buy_price,
                        'shares': remaining_shares,
                        'amount': remaining_shares * buy_price,
                        'reason': f'网格买入，价格{buy_price}'
                    })
                    break

        # 检查卖出信号：完整或部分买入的网格都可以按实际股数退出。
        if current_shares > 0:
            for sell_price in self.sell_grids:
                if current_price >= sell_price:
                    for buy_price in self.buy_grids:
                        grid_shares = self.grid_ledger[buy_price].get('shares', 0)
                        if grid_shares > 0:
                            sell_shares = min(grid_shares, current_shares)
                            signals.append({
                                'action': 'sell',
                                'symbol': self.symbol,
                                'price': sell_price,
                                'shares': sell_shares,
                                'amount': sell_shares * sell_price,
                                'reason': f'网格卖出，价格{sell_price}'
                            })
                            break
                    break

        return signals

    def calc_position_size(self, capital: float, price: float) -> int:
        return self.shares_per_grid

    def _trade_shares(self, trade: dict) -> int:
        shares = trade.get('shares', 0)
        if shares > 0:
            return int(shares / 100) * 100
        price = trade.get('price', 0)
        amount = trade.get('amount', 0)
        if price <= 0 or amount <= 0:
            return 0
        return int(amount / price / 100) * 100

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
            state = dict(ledger.get(str(grid_price), {}))
            shares = state.get(
                'shares',
                self.shares_per_grid if state.get('bought') else 0,
            )
            restored_ledger[grid_price] = {
                'bought': shares >= self.shares_per_grid,
                'sold': False,
                'shares': shares,
            }
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
