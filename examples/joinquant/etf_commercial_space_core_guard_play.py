"""JoinQuant play script for commercial-space ETF core guard.

复制到聚宽策略编辑器运行。本脚本用于复验
`RQO-20260629-commercial-space-launch-window` 的公开平台口径，不是实盘交易建议。

本地筛选参考：

- 标的：159206，永赢国证商用卫星通信产业 ETF。
- 数据：本地 provider 导出日线，2024-01-01 至 2026-06-26。
- 候选：daily_core_guard，按 PASS 候选中最大回撤优先选择。
- 本地 sanity：年化约 8.99%，最大回撤约 12.37%，纯现金日约 70.83%。

策略设计：

- 每日开盘评估，常规调仓至少间隔 5 个交易日。
- 沪深 300 趋势转弱，或 159206 自身跌破 80 日均线时保持现金。
- 风险开启时只持有 159206，目标仓位 50%，其余保持现金。
- 这是事件驱动主题的纸面跟踪脚本，重点观察是否只在趋势确认后参与。
"""

import math


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    g.strategy_id = "ETF-COMMERCIAL-SPACE-CORE-GUARD-PLAY"
    g.etf_pool = ["159206.XSHE"]
    g.market_proxy = "510300.XSHG"

    g.fast_window = 20
    g.slow_window = 60
    g.trend_window = 80
    g.market_trend_window = 120
    g.breadth_window = 80
    g.breadth_threshold = 0.50
    g.vol_window = 60
    g.drawdown_window = 60
    g.max_recent_drawdown = 0.12
    g.min_rebalance_gap_days = 5
    g.max_holdings = 1
    g.target_exposure = 0.50
    g.target_completion_tolerance = 0.02
    g.min_switch_score_gap = 0.01
    g.min_avg_money = 0
    g.slippage_rate = 0.001

    g.current_targets = []
    g.current_target_exposure = 0
    g.days_since_rebalance = 999
    g.last_trade_date = None
    g.debug = True
    g.debug_count = 0
    g.debug_limit = 8

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

    market_ok, market_reason, market_strength, breadth = market_regime()
    actual_positions = current_position_symbols(context)
    if not market_ok:
        if actual_positions:
            log.info("%s %s, clear positions" % (g.strategy_id, market_reason))
            sell_all(context)
            g.current_targets = []
            g.current_target_exposure = 0
            g.days_since_rebalance = 0
        else:
            g.current_targets = []
            g.current_target_exposure = 0
        return

    if (
        g.days_since_rebalance < g.min_rebalance_gap_days
        and target_positions_complete(context, g.current_targets, g.target_exposure)
    ):
        return

    ranked = rank_candidates(context)
    selected = [item["security"] for item in ranked[: g.max_holdings]]

    log.info(
        "%s selected=%s exposure=%.2f market_strength=%.4f breadth=%.2f"
        % (
            g.strategy_id,
            selected,
            g.target_exposure if selected else 0,
            market_strength,
            breadth,
        )
    )
    apply_targets(context, selected, g.target_exposure if selected else 0)
    g.current_targets = selected
    g.current_target_exposure = g.target_exposure if selected else 0
    g.days_since_rebalance = 0


def market_regime():
    hist = history_frame(g.market_proxy, g.market_trend_window)
    if hist is None or "close" not in hist:
        return False, "market missing history", 0, 0
    close = hist["close"].dropna()
    if len(close) < g.market_trend_window:
        return False, "market insufficient history", 0, 0

    latest = float(close.iloc[-1])
    market_ma = float(close.iloc[-g.market_trend_window :].mean())
    if latest <= 0 or market_ma <= 0:
        return False, "market invalid price", 0, 0
    market_strength = latest / market_ma - 1.0
    if latest < market_ma:
        return False, "market trend weak", market_strength, 0

    breadth = trend_breadth()
    if breadth is None:
        return False, "breadth insufficient history", market_strength, 0
    if breadth < g.breadth_threshold:
        return False, "breadth weak %.2f" % breadth, market_strength, breadth
    return True, "risk on", market_strength, breadth


def trend_breadth():
    valid_count = 0
    above_count = 0
    for security in g.etf_pool:
        hist = history_frame(security, g.breadth_window)
        if hist is None or "close" not in hist:
            continue
        close = hist["close"].dropna()
        if len(close) < g.breadth_window:
            continue
        latest = float(close.iloc[-1])
        moving_average = float(close.iloc[-g.breadth_window :].mean())
        if latest <= 0 or moving_average <= 0:
            continue
        valid_count += 1
        if latest >= moving_average:
            above_count += 1
    if valid_count == 0:
        return None
    return float(above_count) / float(valid_count)


def rank_candidates(context):
    candidates = []
    rejections = []
    held_symbols = set(current_position_symbols(context))
    for security in g.etf_pool:
        item, reason = candidate_factor(security, security in held_symbols)
        if item is None:
            rejections.append((security, reason))
        else:
            candidates.append(item)
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    log_diagnostics(ranked, rejections)
    return ranked


def candidate_factor(security, already_held=False):
    tradable, reason = can_trade_detail(
        security,
        allow_high_limit=already_held,
    )
    if not tradable:
        return None, reason

    min_history_days = max(
        g.slow_window + 1,
        g.trend_window,
        g.vol_window + 1,
        g.drawdown_window,
    )
    hist = history_frame(security, min_history_days)
    if hist is None or "close" not in hist or "money" not in hist:
        return None, "missing_history"

    close = hist["close"].dropna()
    money = hist["money"].dropna()
    if len(close) < min_history_days:
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


def apply_targets(context, selected, target_exposure):
    for security in list(context.portfolio.positions.keys()):
        if security not in selected:
            order_target_value(security, 0)

    if not selected or target_exposure <= 0:
        return

    target_value = (
        context.portfolio.total_value * target_exposure / float(len(selected))
    )
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


def target_positions_complete(context, selected, target_exposure):
    actual_positions = current_position_symbols(context)
    if actual_positions != sorted(selected):
        return False
    if not selected:
        return True

    total_value = context.portfolio.total_value
    if total_value <= 0:
        return False
    target_value = total_value * target_exposure / float(len(selected))
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


def can_trade_detail(security, allow_high_limit=False):
    current_data = get_current_data()
    if security not in current_data:
        return False, "not_in_current_data"
    data = current_data[security]
    if data.paused:
        return False, "paused"
    if data.last_price is None or data.last_price <= 0:
        return False, "invalid_last_price"
    if data.high_limit is not None and data.last_price >= data.high_limit:
        if allow_high_limit:
            return True, "held_at_high_limit"
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
