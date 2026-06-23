"""JoinQuant diagnostic script for ETF adaptive exposure guard.

复制到聚宽策略编辑器运行。本脚本是失败复盘材料，不是候选策略推荐。

公开平台复验结论：

- 2019-01-02 至 2026-06-22：年化约 3.94%，最大回撤约 22.94%。
- 2022-01-04 至 2026-06-22：年化约 3.99%，最大回撤约 18.40%。
- 收益与回撤均不满足稳健 ETF 准入门槛，暂不推进模拟盘。

保留本脚本的目的，是复现和排查本地筛选与聚宽结果差异，重点关注复权口径、候选池数据、成交/调仓日对齐。

策略设计仍保持 ETF 主线：

- 只在 ETF 池内选 1 只趋势/相对强度较好的 ETF。
- 不引入债券、黄金或类存款资产压回撤；弱市通过降仓或空仓控制风险。
- 每日开盘评估风险，但常规调仓至少间隔 20 个交易日。
- 市场趋势和 ETF 池广度通过后，根据趋势强度把 ETF 目标仓位分层。

本文件依赖聚宽云端 API，本地只做语法检查。
"""

import math


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    g.strategy_id = "ETF-ADAPT-EXP-007"
    g.etf_pool = [
        "510300.XSHG",  # 沪深300 ETF
        "510500.XSHG",  # 中证500 ETF
        "159915.XSHE",  # 创业板 ETF
        "512880.XSHG",  # 证券 ETF
        "512800.XSHG",  # 银行 ETF
        "512000.XSHG",  # 券商 ETF
        "159928.XSHE",  # 消费 ETF
    ]
    g.market_proxy = "510300.XSHG"

    # 默认使用本地筛选中样本内表现较稳的一组：
    # interval=20 fast=40 slow=120 trend=120 market=160 exposure=0.8。
    g.fast_window = 40
    g.slow_window = 120
    g.trend_window = 120
    g.market_trend_window = 160
    g.breadth_window = 120
    g.breadth_threshold = 0.50
    g.vol_window = 60
    g.drawdown_window = 60
    g.max_recent_drawdown = 0.16
    g.min_rebalance_gap_days = 20
    g.max_holdings = 1
    g.base_target_exposure = 0.80
    g.min_avg_money = 0
    g.target_completion_tolerance = 0.02
    g.min_switch_score_gap = 0.01
    g.slippage_rate = 0.001

    g.current_targets = []
    g.current_target_exposure = 0
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

    if g.days_since_rebalance < g.min_rebalance_gap_days:
        retry_exposure = adaptive_target_exposure(market_strength, breadth)
        g.current_target_exposure = retry_exposure
        if target_positions_complete(
            context,
            g.current_targets,
            retry_exposure,
        ):
            return
        log.info(
            "%s retry targets=%s exposure=%.2f"
            % (g.strategy_id, g.current_targets, retry_exposure)
        )
        apply_targets(context, g.current_targets, retry_exposure)
        return

    ranked = rank_candidates()
    selected = stabilized_selection(ranked, actual_positions)
    target_exposure = adaptive_target_exposure(market_strength, breadth)

    log.info(
        "%s selected=%s exposure=%.2f market_strength=%.4f breadth=%.2f"
        % (g.strategy_id, selected, target_exposure, market_strength, breadth)
    )
    apply_targets(context, selected, target_exposure)
    g.current_targets = selected
    g.current_target_exposure = target_exposure
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


def adaptive_target_exposure(market_strength, breadth):
    if (
        market_strength >= 0.06
        and breadth >= min(g.breadth_threshold + 0.25, 1.0)
    ):
        return g.base_target_exposure
    if (
        market_strength >= 0.02
        and breadth >= min(g.breadth_threshold + 0.10, 1.0)
    ):
        return g.base_target_exposure * 0.75
    return g.base_target_exposure * 0.50


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


def stabilized_selection(ranked, actual_positions):
    default = [item["security"] for item in ranked[: g.max_holdings]]
    if g.min_switch_score_gap <= 0 or not actual_positions:
        return default
    ranked_by_security = {}
    for item in ranked:
        ranked_by_security[item["security"]] = item

    current = []
    for security in actual_positions:
        if security in ranked_by_security:
            current.append(security)
        if len(current) >= g.max_holdings:
            break
    if len(current) != len(default):
        return default

    default_score = average_score(
        [ranked_by_security[security] for security in default]
    )
    current_score = average_score(
        [ranked_by_security[security] for security in current]
    )
    if default_score - current_score < g.min_switch_score_gap:
        return current
    return default


def average_score(items):
    if not items:
        return -999999
    return sum([item["score"] for item in items]) / float(len(items))


def apply_targets(context, selected, target_exposure):
    for security in list(context.portfolio.positions.keys()):
        if security not in selected:
            order_target_value(security, 0)

    if not selected:
        return

    target_value = context.portfolio.total_value * target_exposure
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


def can_trade_detail(security):
    current_data = get_current_data()
    if security not in current_data:
        return True, "current_data_missing_assume_tradable"
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
