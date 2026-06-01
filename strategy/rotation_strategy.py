from datetime import datetime
from .base import BaseStrategy


class RotationStrategy(BaseStrategy):

    def __init__(self, config):
        super().__init__(config)
        self.etf_pool = config['etf_pool']
        self.lookback = config.get('lookback', 20)
        self.top_n = config.get('top_n', 3)
        self.rebalance_days = config.get('rebalance_days', 30)
        self.selected_etfs = []
        self.last_rebalance = None

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        signals = []
        if self.need_rebalance():
            momentum = self.calculate_momentum(data)
            if not momentum:
                return []
            self.selected_etfs = self.select_top_etfs(momentum)
            if not self.selected_etfs:
                return []
            signals = self.generate_rebalance_signals(data)
            if signals:
                self.last_rebalance = datetime.now()
        return signals

    def calculate_momentum(self, data: dict) -> dict:
        momentum = {}
        for symbol in self.etf_pool:
            if symbol in data:
                prices = data[symbol].get('prices', [])
                if len(prices) >= self.lookback:
                    returns = (prices[-1] - prices[-self.lookback]) / prices[-self.lookback]
                    momentum[symbol] = returns
        return momentum

    def select_top_etfs(self, momentum: dict) -> list:
        sorted_etfs = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
        return [etf[0] for etf in sorted_etfs[:self.top_n]]

    def generate_rebalance_signals(self, data: dict = None) -> list:
        signals = []
        # 只计算有价格数据的 symbol
        valid_symbols = []
        symbol_prices = {}
        for symbol in self.selected_etfs:
            if data and symbol in data:
                price = data[symbol].get('price', 0)
                if price > 0:
                    valid_symbols.append(symbol)
                    symbol_prices[symbol] = price

        if not valid_symbols:
            return []

        weight = 1.0 / len(valid_symbols)
        for symbol in valid_symbols:
            signals.append({
                'action': 'rebalance',
                'symbol': symbol,
                'target_weight': weight,
                'price': symbol_prices[symbol],
                'reason': '行业轮动调仓'
            })
        return signals

    def need_rebalance(self) -> bool:
        if self.last_rebalance is None:
            return True
        days_since = (datetime.now() - self.last_rebalance).days
        return days_since >= self.rebalance_days

    def calc_position_size(self, capital: float, price: float) -> int:
        target_capital = capital * (1.0 / len(self.selected_etfs)) if self.selected_etfs else 0
        shares = int(target_capital / price / 100) * 100
        return shares
