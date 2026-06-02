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
        self.pending_rebalance_count = 0

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        signals = []
        if self.need_rebalance(data):
            momentum = self.calculate_momentum(data)
            if not momentum:
                return []
            self.selected_etfs = self.select_top_etfs(momentum)
            if not self.selected_etfs:
                return []
            signals = self.generate_rebalance_signals(data, portfolio)
            if signals:
                self.pending_rebalance_count = len(signals)
        return signals

    def on_trade_confirmed(self, trade: dict):
        """交易确认后更新 rebalance 状态"""
        if self.pending_rebalance_count > 0:
            self.pending_rebalance_count -= 1
            if self.pending_rebalance_count == 0:
                self.last_rebalance = self._resolve_datetime(trade) or datetime.now()

    def on_trade_failed(self, trade: dict):
        """交易失败后递减 pending，允许重试"""
        if self.pending_rebalance_count > 0:
            self.pending_rebalance_count -= 1

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

    def generate_rebalance_signals(self, data: dict = None, portfolio: dict = None) -> list:
        signals = []
        signal_time = self._resolve_datetime(data)

        # 先生成卖出信号：已持有但不在 selected_etfs 中的
        if portfolio:
            positions = portfolio.get('positions', {})
            for symbol, pos in positions.items():
                if symbol not in self.selected_etfs and pos.get('shares', 0) > 0:
                    price = 0
                    if data and symbol in data:
                        price = data[symbol].get('price', 0)
                    if price <= 0:
                        price = pos.get('current_price', pos.get('avg_price', 0))
                    if price > 0:
                        signals.append({
                            'action': 'sell',
                            'symbol': symbol,
                            'price': price,
                            'shares': pos['shares'],
                            'amount': pos['shares'] * price,
                            'reason': '行业轮动调仓(卖出跌出top_n)',
                            'timestamp': signal_time,
                        })

        # 再生成买入信号：新选中的 ETF
        valid_buy_symbols = []
        symbol_prices = {}
        for symbol in self.selected_etfs:
            if data and symbol in data:
                price = data[symbol].get('price', 0)
                if price > 0:
                    valid_buy_symbols.append(symbol)
                    symbol_prices[symbol] = price

        if valid_buy_symbols:
            buy_weight = 1.0 / len(valid_buy_symbols)
            # 计算可用于买入的总金额 = 当前现金 + 预计卖出所得
            capital = portfolio.get('capital', 0) if portfolio else 0
            sold_value = sum(
                s.get('amount', 0) for s in signals if s.get('action') == 'sell'
            )
            available_capital = capital + sold_value

            for symbol in valid_buy_symbols:
                target_amount = available_capital * buy_weight
                price = symbol_prices[symbol]
                shares = int(target_amount / price / 100) * 100
                signals.append({
                    'action': 'buy',
                    'symbol': symbol,
                    'price': price,
                    'shares': shares,
                    'amount': shares * price,
                    'reason': '行业轮动调仓(买入)',
                    'timestamp': signal_time,
                })

        return signals

    def need_rebalance(self, data: dict = None) -> bool:
        if self.pending_rebalance_count > 0:
            return False
        if self.last_rebalance is None:
            return True
        current_time = self._resolve_datetime(data) or datetime.now()
        days_since = (current_time - self.last_rebalance).days
        return days_since >= self.rebalance_days

    def _resolve_datetime(self, payload: dict = None):
        if not isinstance(payload, dict):
            return None
        value = (
            payload.get('timestamp')
            or payload.get('date')
            or payload.get('_timestamp')
            or payload.get('_date')
        )
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value)
        return None

    def calc_position_size(self, capital: float, price: float) -> int:
        target_capital = capital * (1.0 / len(self.selected_etfs)) if self.selected_etfs else 0
        shares = int(target_capital / price / 100) * 100
        return shares

    def snapshot(self) -> dict:
        return {
            'version': 1,
            'type': 'RotationStrategy',
            'name': self.name,
            'symbol': self.symbol,
            'selected_etfs': list(self.selected_etfs),
            'last_rebalance': (
                self.last_rebalance.isoformat()
                if self.last_rebalance else None
            ),
            'pending_rebalance_count': self.pending_rebalance_count,
            'trades': self._serialize_trades(),
        }

    def restore(self, snapshot: dict):
        if snapshot.get('version') != 1:
            raise ValueError('不支持的 RotationStrategy 状态版本')
        self.selected_etfs = list(snapshot.get('selected_etfs', []))
        self.last_rebalance = self._resolve_datetime({
            'timestamp': snapshot.get('last_rebalance')
        })
        self.pending_rebalance_count = snapshot.get('pending_rebalance_count', 0)
        self._restore_trades(snapshot.get('trades', []))
