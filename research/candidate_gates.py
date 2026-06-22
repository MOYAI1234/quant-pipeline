import math
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateGateConfig:
    """本地候选进入公开平台复验前的默认准入门槛。"""

    min_annual_return: float = 0.06
    max_drawdown: float = 0.15
    max_annual_turnover: float = 8.0
    max_annual_commission_ratio: float = 0.005
    max_trades_per_day: int = 2
    min_trade_count: int = 4
    max_cash_day_ratio: float = 0.80

    def __post_init__(self):
        _validate_ratio('min_annual_return', self.min_annual_return, minimum=-1)
        _validate_ratio('max_drawdown', self.max_drawdown)
        _validate_ratio('max_annual_turnover', self.max_annual_turnover)
        _validate_ratio(
            'max_annual_commission_ratio',
            self.max_annual_commission_ratio,
        )
        _validate_ratio('max_cash_day_ratio', self.max_cash_day_ratio, maximum=1)
        if (
            isinstance(self.max_trades_per_day, bool)
            or not isinstance(self.max_trades_per_day, int)
            or self.max_trades_per_day < 1
        ):
            raise ValueError('max_trades_per_day 必须是大于 0 的整数')
        if (
            isinstance(self.min_trade_count, bool)
            or not isinstance(self.min_trade_count, int)
            or self.min_trade_count < 0
        ):
            raise ValueError('min_trade_count 必须是非负整数')


@dataclass(frozen=True)
class CandidateGateDecision:
    status: str
    reasons: tuple[str, ...]
    annual_turnover: float
    annual_commission_ratio: float
    max_daily_trades: int
    cash_day_ratio: float

    @property
    def passed(self) -> bool:
        return self.status == 'PASS'


def evaluate_candidate(
    metrics: dict,
    config: CandidateGateConfig | None = None,
) -> CandidateGateDecision:
    config = config or CandidateGateConfig()
    years = _finite_metric(metrics, 'years', positive=True)
    annual_return = _finite_metric(metrics, 'annual_return')
    max_drawdown = _finite_metric(metrics, 'max_drawdown')
    turnover_ratio = _finite_metric(metrics, 'turnover_ratio')
    commission_ratio = _finite_metric(metrics, 'commission_ratio')
    trade_count = _integer_metric(metrics, 'trade_count')
    trades = metrics.get('trades')
    portfolio_curve = metrics.get('portfolio_curve')
    if not isinstance(trades, list):
        raise ValueError('trades 必须是列表')
    if trade_count != len(trades):
        raise ValueError('trade_count 必须与 trades 长度一致')
    if not isinstance(portfolio_curve, list) or not portfolio_curve:
        raise ValueError('portfolio_curve 必须是非空列表')

    annual_turnover = turnover_ratio / years
    annual_commission_ratio = commission_ratio / years
    max_daily_trades = _max_daily_trades(trades)
    cash_day_ratio = _cash_day_ratio(portfolio_curve)

    structural_reasons = []
    if trade_count < config.min_trade_count:
        structural_reasons.append(
            f'交易次数 {trade_count} 少于最低样本 {config.min_trade_count}'
        )
    if max_daily_trades > config.max_trades_per_day:
        structural_reasons.append(
            f'单日最多成交 {max_daily_trades} 笔，超过上限 {config.max_trades_per_day}'
        )
    if annual_turnover > config.max_annual_turnover:
        structural_reasons.append(
            f'年化成交额/初始资金 {annual_turnover:.2%} 超过上限 '
            f'{config.max_annual_turnover:.2%}'
        )
    if annual_commission_ratio > config.max_annual_commission_ratio:
        structural_reasons.append(
            f'年化费用/初始资金 {annual_commission_ratio:.2%} 超过上限 '
            f'{config.max_annual_commission_ratio:.2%}'
        )
    if cash_day_ratio > config.max_cash_day_ratio:
        structural_reasons.append(
            f'纯现金日占比 {cash_day_ratio:.2%} 超过上限 '
            f'{config.max_cash_day_ratio:.2%}'
        )

    performance_reasons = []
    if annual_return < config.min_annual_return:
        performance_reasons.append(
            f'年化收益 {annual_return:.2%} 低于目标 {config.min_annual_return:.2%}'
        )
    if max_drawdown > config.max_drawdown:
        performance_reasons.append(
            f'最大回撤 {max_drawdown:.2%} 超过上限 {config.max_drawdown:.2%}'
        )

    if structural_reasons:
        status = 'REJECT'
        reasons = structural_reasons + performance_reasons
    elif performance_reasons:
        status = 'WATCHLIST'
        reasons = performance_reasons
    else:
        status = 'PASS'
        reasons = ['满足本地准入门槛，可进入公开平台复验']
    return CandidateGateDecision(
        status=status,
        reasons=tuple(reasons),
        annual_turnover=annual_turnover,
        annual_commission_ratio=annual_commission_ratio,
        max_daily_trades=max_daily_trades,
        cash_day_ratio=cash_day_ratio,
    )


def _max_daily_trades(trades: list[dict]) -> int:
    counts = Counter()
    for trade in trades:
        if not isinstance(trade, dict):
            raise ValueError('trades 中每项必须是字典')
        timestamp = trade.get('timestamp')
        if not isinstance(timestamp, str) or len(timestamp) < 10:
            raise ValueError('trade.timestamp 必须包含 ISO 日期')
        counts[timestamp[:10]] += 1
    return max(counts.values(), default=0)


def _cash_day_ratio(portfolio_curve: list[dict]) -> float:
    cash_days = 0
    for point in portfolio_curve:
        if not isinstance(point, dict):
            raise ValueError('portfolio_curve 中每项必须是字典')
        total_value = _finite_metric(point, 'total_value', positive=True)
        positions_value = _finite_metric(point, 'positions_market_value')
        if positions_value < 0:
            raise ValueError('positions_market_value 不能为负数')
        if positions_value / total_value <= 0.01:
            cash_days += 1
    return cash_days / len(portfolio_curve)


def _finite_metric(metrics: dict, key: str, positive: bool = False) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} 必须是有限数字')
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        qualifier = '大于 0 的' if positive else ''
        raise ValueError(f'{key} 必须是{qualifier}有限数字')
    return value


def _integer_metric(metrics: dict, key: str) -> int:
    value = _finite_metric(metrics, key)
    if value < 0 or not value.is_integer():
        raise ValueError(f'{key} 必须是非负整数')
    return int(value)


def _validate_ratio(
    name: str,
    value: float,
    minimum: float = 0,
    maximum: float | None = None,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ValueError(f'{name} 超出有效范围')
