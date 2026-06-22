"""JoinQuant script for ETF-EQ-MOM-GUARD-006.

复制到聚宽策略编辑器运行。本策略是 ETF 主线下的权益 ETF 动量防守：

- 每日开盘评估风险，但常规调仓至少间隔 20 个交易日。
- 只在权益 ETF 池内选 1 只最强 ETF；弱市时清仓，不默认买债券或黄金。
- 市场过滤：沪深 300 ETF 跌破 200 日均线时空仓。
- 标的过滤：60 日和 120 日动量都为正，且站上 200 日均线。

本文件依赖聚宽云端 API，本地只做语法检查。
"""

import math


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    g.strategy_id = "ETF-EQ-MOM-GUARD-006"
    g.etf_pool = [
        "510300.XSHG",  # 沪深300 ETF
        "510500.XSHG",  # 中证500 ETF
        "510050.XSHG",  # 上证50 ETF
        "510880.XSHG",  # 红利 ETF
        "159915.XSHE",  # 创业板 ETF
        "159919.XSHE",  # 沪深300 ETF 深市
        "512880.XSHG",  # 证券 ETF
        "512800.XSHG",  # 银行 ETF
        "512660.XSHG",  # 军工 ETF
        "512010.XSHG",  # 医药 ETF
        "159928.XSHE",  # 消费 ETF
        "159929.XSHE",  # 医药 ETF 深市
    ]
    g.market_proxy = "510300.XSHG"

    g.fast_window = 60
    g.slow_window = 120
    g.trend_window = 200
    g.market_trend_window = 200
    g.vol_window = 60
    g.drawdown_window = 60
    g.max_recent_drawdown = 0.18
    g.min_history_days = 201
    g.min_rebalance_gap_days = 20
    g.max_holdings = 1
    g.target_exposure = 1.0
    g.target_completion_tolerance = 0.02
    g.min_avg_money = 0
    g.slippage_rate = 0.001

    g.current_targets = []
    g.days_since_rebalance = 999
    g.last_trade_date = None
    g.debug = True
    g.debug_count = 0
    g.debug_limit = 12

    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    set_slippage(PriceRelatedSlippage(g.slippage_rate), type="fund")
    set_option("order_volume_ratio", 0.05)

    run_daily(rebalance, time="open")


def rebalance(context):
    today = context.current_dt.date()
    if g.last_trade_date == today:
        return
    g.last_trade_date = today
    g.days_since_rebalance += 1
    actual_positions = current_position_symbols(context)

    if not market_is_healthy():
        if actual_positions:
            log.info("%s market weak, clear positions" % g.strategy_id)
            sell_all(context)
            g.days_since_rebalance = 0
        else:
            g.current_targets = []
        return

    if (
        g.days_since_rebalance < g.min_rebalance_gap_days
        and target_positions_complete(context, g.current_targets)
    ):
        return

    ranked = rank_candidates()
    selected = [item["security"] for item in ranked[: g.max_holdings]]
    log.info("%s selected targets: %s" % (g.strategy_id, selected))

    actual_positions = current_position_symbols(context)
    if (
        selected == g.current_targets
        and target_positions_complete(context, selected)
    ):
        g.days_since_rebalance = 0
        log.info("%s targets unchanged, skip rebalance" % g.strategy_id)
        return

    apply_targets(context, selected)
    g.current_targets = selected
    g.days_since_rebalance = 0


def market_is_healthy():
    hist = history_frame(g.market_proxy, g.market_trend_window)
    if hist is None:
        return False
    close = hist["close"].dropna()
    if len(close) < g.market_trend_window:
        return False
    latest = float(close.iloc[-1])
    moving_average = float(close.iloc[-g.market_trend_window :].mean())
    return latest > 0 and moving_average > 0 and latest >= moving_average


def rank_candidates():
    candidates = []
    rejections = []
    for security in g.etf_pool:
        item, reason = candidate_factor(security)
        if item is None:
            rejections.append((security, reason))
        else:
            candidates.append(item)
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    log_diagnostics(ranked, rejections)
    return ranked


def candidate_factor(security):
    tradable, reason = can_trade_detail(security)
    if not tradable:
        return None, reason

    hist = history_frame(security, g.min_history_days)
    if hist is None or "close" not in hist or "money" not in hist:
        return None, "missing_history"

    close = hist["close"].dropna()
    money = hist["money"].dropna()
    if len(close) < g.min_history_days:
        return None, "insufficient_history"

    if g.min_avg_money > 0 and len(money) >= 20:
        avg_money = float(money.iloc[-20:].mean())
        if avg_money < g.min_avg_money:
            return None, "low_avg_money"
    else:
        avg_money = 0

    latest = float(close.iloc[-1])
    fast_base = float(close.iloc[-g.fast_window - 1])
    slow_base = float(close.iloc[-g.slow_window - 1])
    trend_ma = float(close.iloc[-g.trend_window :].mean())
    recent_high = float(close.iloc[-g.drawdown_window :].max())
    if latest <= 0 or fast_base <= 0 or slow_base <= 0 or trend_ma <= 0:
        return None, "invalid_price"

    fast_momentum = latest / fast_base - 1.0
    slow_momentum = latest / slow_base - 1.0
    recent_drawdown = latest / recent_high - 1.0
    if fast_momentum <= 0 or slow_momentum <= 0:
        return None, "non_positive_momentum"
    if latest < trend_ma:
        return None, "below_own_trend"
    if recent_drawdown <= -g.max_recent_drawdown:
        return None, "recent_drawdown_too_deep"

    returns = close.pct_change().dropna()
    volatility = float(returns.iloc[-g.vol_window :].std())
    if math.isnan(volatility) or volatility <= 0:
        return None, "invalid_volatility"

    score = fast_momentum * 0.45 + slow_momentum * 0.45
    score += recent_drawdown * 0.20
    score -= volatility * 2.0
    return {
        "security": security,
        "score": score,
        "fast_momentum": fast_momentum,
        "slow_momentum": slow_momentum,
        "recent_drawdown": recent_drawdown,
        "volatility": volatility,
        "avg_money": avg_money,
    }, None


def apply_targets(context, selected):
    for security in list(context.portfolio.positions.keys()):
        if security not in selected:
            order_target_value(security, 0)

    if not selected:
        return

    target_value = context.portfolio.total_value * g.target_exposure
    for security in selected:
        if can_trade(security):
            order_target_value(security, target_value)


def sell_all(context):
    for security in list(context.portfolio.positions.keys()):
        order_target_value(security, 0)


def current_position_symbols(context):
    positions = []
    for security, position in context.portfolio.positions.items():
        if position.total_amount > 0:
            positions.append(security)
    return sorted(positions)


def target_positions_complete(context, selected):
    actual_positions = current_position_symbols(context)
    if actual_positions != sorted(selected):
        return False
    if not selected:
        return True

    total_value = context.portfolio.total_value
    if total_value <= 0:
        return False
    target_value = total_value * g.target_exposure / len(selected)
    tolerance = max(target_value * g.target_completion_tolerance, 100)
    for security in selected:
        position = context.portfolio.positions.get(security)
        if position is None or position.total_amount <= 0:
            return False
        current_value = position_value(position)
        if abs(current_value - target_value) > tolerance:
            return False
    return True


def position_value(position):
    for attr in ["value", "market_value"]:
        value = getattr(position, attr, None)
        if value is not None:
            return float(value)
    price = 0
    for attr in ["price", "current_price", "last_price", "avg_cost"]:
        value = getattr(position, attr, None)
        if value is not None and value > 0:
            price = float(value)
            break
    return float(position.total_amount) * price


def history_frame(security, count):
    try:
        return attribute_history(
            security,
            count,
            unit="1d",
            fields=["close", "money"],
            skip_paused=True,
            df=True,
            fq="pre",
        )
    except Exception as exc:
        log.info("history error %s: %s" % (security, exc))
        return None


def can_trade(security):
    tradable, _ = can_trade_detail(security)
    return tradable


def can_trade_detail(security):
    current_data = get_current_data()
    if security not in current_data:
        return False, "not_in_current_data"
    data = current_data[security]
    if data.paused:
        return False, "paused"
    if data.last_price is None or data.last_price <= 0:
        return False, "invalid_last_price"
    if data.high_limit is not None and data.last_price >= data.high_limit:
        return False, "at_high_limit"
    if data.low_limit is not None and data.last_price <= data.low_limit:
        return False, "at_low_limit"
    return True, "tradable"


def log_diagnostics(ranked, rejections):
    if not g.debug or g.debug_count >= g.debug_limit:
        return
    g.debug_count += 1
    log.info("factor diagnostics begin")
    for item in ranked:
        log.info(
            "%s score=%.4f fast=%.4f slow=%.4f drawdown=%.4f vol=%.4f avg_money=%.2f"
            % (
                item["security"],
                item["score"],
                item["fast_momentum"],
                item["slow_momentum"],
                item["recent_drawdown"],
                item["volatility"],
                item["avg_money"],
            )
        )
    for security, reason in rejections:
        log.info("reject %s: %s" % (security, reason))
