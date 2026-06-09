import math
from dataclasses import dataclass


@dataclass
class ExecutionDecision:
    accepted: bool
    signal: dict
    rejection_reason: str | None = None


class BacktestExecutionModel:

    def __init__(
        self,
        slippage_rate: float = 0.0,
        max_volume_participation: float | None = None,
    ):
        self.slippage_rate = _validate_slippage_rate(slippage_rate)
        self.max_volume_participation = _validate_volume_participation(
            max_volume_participation
        )

    @classmethod
    def from_account_config(cls, account_config: dict):
        return cls(
            slippage_rate=account_config.get('slippage_rate', 0.0),
            max_volume_participation=account_config.get(
                'max_volume_participation'
            ),
        )

    def build_volume_limits(self, volumes: dict) -> dict | None:
        return _build_volume_limits(volumes, self.max_volume_participation)

    def prepare_order(
        self,
        signal: dict,
        volume_limits: dict | None = None,
    ) -> ExecutionDecision:
        execution_signal = _apply_slippage(signal, self.slippage_rate)
        if not _signal_within_volume_limit(execution_signal, volume_limits):
            return ExecutionDecision(
                accepted=False,
                signal=execution_signal,
                rejection_reason='volume_limit',
            )
        return ExecutionDecision(accepted=True, signal=execution_signal)

    def consume_fill(self, signal: dict, volume_limits: dict | None) -> None:
        _consume_signal_volume(signal, volume_limits)


def _apply_slippage(signal: dict, slippage_rate: float) -> dict:
    if slippage_rate == 0:
        return signal
    execution_signal = dict(signal)
    price = execution_signal.get('price', 0)
    if price <= 0:
        return execution_signal

    if execution_signal.get('action') == 'buy':
        execution_price = price * (1 + slippage_rate)
    elif execution_signal.get('action') == 'sell':
        execution_price = price * (1 - slippage_rate)
    else:
        execution_price = price

    execution_signal['price'] = execution_price
    if execution_signal.get('shares', 0) > 0:
        execution_signal['amount'] = execution_signal['shares'] * execution_price
    return execution_signal


def _validate_slippage_rate(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or value >= 1
    ):
        raise ValueError('slippage_rate 必须在 0 到 1 之间，且小于 1')
    return float(value)


def _validate_volume_participation(value: float | None) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
        or value > 1
    ):
        raise ValueError('max_volume_participation 必须大于 0 且不大于 1')
    return float(value)


def _build_volume_limits(
    volumes: dict,
    max_volume_participation: float | None,
) -> dict | None:
    if max_volume_participation is None:
        return None
    return {
        symbol: volume * max_volume_participation
        for symbol, volume in volumes.items()
    }


def _signal_within_volume_limit(
    signal: dict,
    volume_limits: dict | None,
) -> bool:
    if volume_limits is None:
        return True
    shares = _signal_shares(signal)
    if shares <= 0:
        return True
    return shares <= volume_limits.get(signal.get('symbol'), 0)


def _consume_signal_volume(signal: dict, volume_limits: dict | None) -> None:
    if volume_limits is None:
        return
    symbol = signal.get('symbol')
    volume_limits[symbol] = max(
        volume_limits.get(symbol, 0) - _signal_shares(signal),
        0,
    )


def _signal_shares(signal: dict) -> int:
    """按 Simulator 的 100 股整手规则计算参与率占用；不足整手返回 0。"""
    shares = signal.get('shares', 0)
    if shares > 0:
        return int(shares / 100) * 100
    price = signal.get('price', 0)
    amount = signal.get('amount', 0)
    if price <= 0 or amount <= 0:
        return 0
    return int(amount / price / 100) * 100
