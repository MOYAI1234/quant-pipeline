import math
from dataclasses import dataclass


@dataclass
class ExecutionDecision:
    accepted: bool
    signal: dict
    rejection_reason: str | None = None
    partial_fill: bool = False


class BacktestExecutionModel:

    def __init__(
        self,
        slippage_rate: float = 0.0,
        max_volume_participation: float | None = None,
        allow_partial_fills: bool = False,
    ):
        self.slippage_rate = _validate_slippage_rate(slippage_rate)
        self.max_volume_participation = _validate_volume_participation(
            max_volume_participation
        )
        self.allow_partial_fills = _validate_allow_partial_fills(
            allow_partial_fills
        )

    @classmethod
    def from_account_config(cls, account_config: dict):
        return cls(
            slippage_rate=account_config.get('slippage_rate', 0.0),
            max_volume_participation=account_config.get(
                'max_volume_participation'
            ),
            allow_partial_fills=account_config.get('allow_partial_fills', False),
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
            if self.allow_partial_fills:
                partial_signal = _fit_signal_to_volume_limit(
                    execution_signal,
                    volume_limits,
                )
                if partial_signal is not None:
                    return ExecutionDecision(
                        accepted=True,
                        signal=partial_signal,
                        partial_fill=True,
                    )
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


def _validate_allow_partial_fills(value: bool) -> bool:
    if not isinstance(value, bool):
        raise ValueError('allow_partial_fills 必须是布尔值')
    return value


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


def _fit_signal_to_volume_limit(
    signal: dict,
    volume_limits: dict | None,
) -> dict | None:
    if volume_limits is None:
        return signal
    price = signal.get('price', 0)
    if price <= 0:
        return None
    limit = volume_limits.get(signal.get('symbol'), 0)
    fillable_shares = int(limit / 100) * 100
    if fillable_shares <= 0:
        return None

    requested_shares = _signal_shares(signal)
    if requested_shares <= 0:
        return None
    shares = min(requested_shares, fillable_shares)
    partial_signal = dict(signal)
    partial_signal['shares'] = shares
    partial_signal['amount'] = shares * price
    partial_signal['partial_fill'] = shares < requested_shares
    partial_signal['requested_shares'] = requested_shares
    return partial_signal


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
