from copy import deepcopy
from datetime import datetime
import math

from strategy.base import BaseStrategy


class DrawdownPauseOverlayStrategy(BaseStrategy):
    """组合回撤触发的清仓与暂停 overlay。"""

    def __init__(
        self,
        strategy,
        *,
        max_drawdown: float = 0.1,
        release_dates: set[str] | None = None,
        name_suffix: str = ' + 回撤暂停',
    ):
        if (
            isinstance(max_drawdown, bool)
            or not isinstance(max_drawdown, (int, float))
            or not math.isfinite(float(max_drawdown))
            or max_drawdown <= 0
            or max_drawdown >= 1
        ):
            raise ValueError('max_drawdown 必须大于 0 且小于 1')

        self.wrapped_strategy = deepcopy(strategy)
        super().__init__({
            'name': self.wrapped_strategy.name + name_suffix,
            'symbol': self.wrapped_strategy.symbol,
        })
        self.etf_pool = list(getattr(self.wrapped_strategy, 'etf_pool', []) or [])
        self.max_drawdown = float(max_drawdown)
        self.release_dates = set(
            release_dates
            if release_dates is not None
            else getattr(self.wrapped_strategy, 'rebalance_dates', set())
        )
        self.peak_value = None
        self.pause_active = False
        self.pause_start_date = None
        self.pause_count = 0
        self.release_count = 0
        self.pauses = []

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        date = _resolve_date(data)
        portfolio = portfolio or {}
        total_value = portfolio.get('total_value')
        if total_value is None:
            return self.wrapped_strategy.generate_signal(data, portfolio)

        if self._should_release(date):
            self.pause_active = False
            self.pause_start_date = None
            self.release_count += 1
            self.peak_value = total_value

        if self._should_pause(total_value, portfolio):
            return self._pause_signals(data, portfolio, total_value, date)

        if self.peak_value is None or total_value > self.peak_value:
            self.peak_value = total_value

        if self.pause_active:
            return []
        return self.wrapped_strategy.generate_signal(data, portfolio)

    def calc_position_size(self, capital: float, price: float) -> int:
        return self.wrapped_strategy.calc_position_size(capital, price)

    def record_trade(self, trade: dict):
        super().record_trade(trade)
        self.wrapped_strategy.record_trade(trade)

    def _should_release(self, date: str) -> bool:
        return (
            self.pause_active
            and bool(date)
            and date in self.release_dates
            and date != self.pause_start_date
        )

    def _should_pause(self, total_value: float, portfolio: dict) -> bool:
        if self.pause_active or self.peak_value in (None, 0):
            return False
        positions = portfolio.get('positions', {})
        if not positions:
            return False
        drawdown = (self.peak_value - total_value) / self.peak_value
        return drawdown >= self.max_drawdown

    def _pause_signals(
        self,
        data: dict,
        portfolio: dict,
        total_value: float,
        date: str,
    ) -> list:
        self.pause_active = True
        self.pause_start_date = date
        self.pause_count += 1
        drawdown = (
            (self.peak_value - total_value) / self.peak_value
            if self.peak_value else 0.0
        )
        self.pauses.append({
            'date': date,
            'drawdown': drawdown,
            'total_value': total_value,
            'peak_value': self.peak_value,
        })
        return _sell_all_signals(
            data,
            portfolio,
            reason='组合回撤暂停触发',
        )


def overlay_diagnostics(strategy: DrawdownPauseOverlayStrategy) -> dict:
    return {
        'pause_count': strategy.pause_count,
        'release_count': strategy.release_count,
        'pause_active': strategy.pause_active,
        'pauses': list(strategy.pauses),
    }


def _sell_all_signals(data: dict, portfolio: dict, *, reason: str) -> list:
    signals = []
    signal_time = data.get('_date') if isinstance(data, dict) else None
    for symbol, position in portfolio.get('positions', {}).items():
        shares = int(position.get('shares', 0) // 100) * 100
        if shares <= 0:
            continue
        price = _price_for(symbol, data, position)
        if price <= 0:
            continue
        signals.append({
            'action': 'sell',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'amount': shares * price,
            'reason': reason,
            'timestamp': signal_time,
        })
    return signals


def _price_for(symbol: str, data: dict, position: dict) -> float:
    if isinstance(data.get(symbol), dict):
        price = data[symbol].get('price', 0)
        if price > 0:
            return price
    return position.get('current_price', position.get('avg_price', 0))


def _resolve_date(data: dict) -> str:
    if not isinstance(data, dict):
        return ''
    value = (
        data.get('_date')
        or data.get('date')
        or data.get('timestamp')
        or ''
    )
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)
