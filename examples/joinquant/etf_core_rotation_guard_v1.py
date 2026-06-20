"""JoinQuant script for ETF-CORE-ROT-GUARD-005.

复制到聚宽策略编辑器运行。策略主线是 ETF 核心池轮动：

- 每日开盘评估一次，目标组合没有变化时不交易。
- 标的以宽基、风格和行业 ETF 为主，不默认加入债券或黄金。
- 用绝对动量、长期均线、近期回撤和波动惩罚过滤高风险状态。

本文件依赖聚宽云端 API，本地只做语法检查。
"""

import math


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    g.strategy_id = "ETF-CORE-ROT-GUARD-005"
    g.etf_pool = [
        "510300.XSHG",  # 沪深300 ETF
        "510500.XSHG",  # 中证500 ETF
        "510050.XSHG",  # 上证50 ETF
        "510880.XSHG",  # 红利 ETF
        "159915.XSHE",  # 创业板 ETF
        "159919.XSHE",  # 沪深300 ETF 深市
        "512100.XSHG",  # 中证1000 ETF
        "512880.XSHG",  # 证券 ETF
        "512800.XSHG",  # 银行 ETF
    ]
    g.market_proxy = "510300.XSHG"

    g.fast_momentum_window = 60
    g.slow_momentum_window = 120
    g.trend_window = 160
    g.vol_window = 60
    g.drawdown_window = 60
    g.min_history_days = 180
    g.min_avg_money = 30000000
    g.max_holdings = 3
    g.max_weight_per_etf = 0.45
    g.min_rebalance_gap_days = 5
    g.max_recent_drawdown = 0.18
    g.market_trend_window = 200
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

    if not market_is_healthy():
        log.info("%s market unhealthy, clear ETF positions" % g.strategy_id)
        sell_all(context)
        g.current_targets = []
        g.days_since_rebalance = 0
        return

    ranked = rank_candidates()
    selected = [item["security"] for item in ranked[: g.max_holdings]]
    selected = [security for security in selected if can_trade(security)]
    log.info("%s selected targets: %s" % (g.strategy_id, selected))

    if selected == g.current_targets and g.days_since_rebalance < g.min_rebalance_gap_days:
        log.info("%s targets unchanged, skip rebalance" % g.strategy_id)
        return

    weights = inverse_vol_weights([item for item in ranked if item["security"] in selected])
    apply_weight_targets(context, weights)
    g.current_targets = selected
    g.days_since_rebalance = 0


def market_is_healthy():
    hist = get_history(g.market_proxy, g.market_trend_window + 1)
    if hist is None:
        return False
    close = hist["close"].dropna()
    if len(close) < g.market_trend_window:
        return False
    latest = float(close.iloc[-1])
    ma = float(close.iloc[-g.market_trend_window :].mean())
    return latest > 0 and ma > 0 and latest >= ma


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

    hist = get_history(security, g.min_history_days)
    if hist is None or "close" not in hist or "money" not in hist:
        return None, "missing_history"

    close = hist["close"].dropna()
    money = hist["money"].dropna()
    if len(close) < g.min_history_days or len(money) < 20:
        return None, "insufficient_history"

    avg_money = float(money.iloc[-20:].mean())
    if avg_money < g.min_avg_money:
        return None, "low_avg_money"

    latest = float(close.iloc[-1])
    fast_base = float(close.iloc[-g.fast_momentum_window - 1])
    slow_base = float(close.iloc[-g.slow_momentum_window - 1])
    trend_ma = float(close.iloc[-g.trend_window :].mean())
    recent_high = float(close.iloc[-g.drawdown_window :].max())
    if latest <= 0 or fast_base <= 0 or slow_base <= 0 or trend_ma <= 0:
        return None, "invalid_price"

    fast_momentum = latest / fast_base - 1.0
    slow_momentum = latest / slow_base - 1.0
    recent_drawdown = latest / recent_high - 1.0
    if latest < trend_ma:
        return None, "below_trend"
    if fast_momentum <= 0 or slow_momentum <= 0:
        return None, "non_positive_momentum"
    if recent_drawdown <= -g.max_recent_drawdown:
        return None, "recent_drawdown_too_deep"

    returns = close.pct_change().dropna()
    volatility = float(returns.iloc[-g.vol_window :].std())
    if math.isnan(volatility) or volatility <= 0:
        return None, "invalid_volatility"

    score = fast_momentum * 0.45 + slow_momentum * 0.45 + recent_drawdown * 0.30
    score -= volatility * 2.0
    return {
        "security": security,
        "fast_momentum": fast_momentum,
        "slow_momentum": slow_momentum,
        "recent_drawdown": recent_drawdown,
        "volatility": volatility,
        "score": score,
        "avg_money": avg_money,
    }, None


def inverse_vol_weights(items):
    if not items:
        return {}

    raw = {}
    total = 0.0
    for item in items:
        inv = 1.0 / item["volatility"]
        raw[item["security"]] = inv
        total += inv

    weights = {}
    for security, value in raw.items():
        weights[security] = min(value / total, g.max_weight_per_etf)
    return weights


def apply_weight_targets(context, weights):
    current_positions = list(context.portfolio.positions.keys())
    for security in current_positions:
        if security not in weights:
            order_target_value(security, 0)

    for security, weight in weights.items():
        if can_trade(security):
            target_value = context.portfolio.total_value * weight
            order_target_value(security, target_value)


def sell_all(context):
    for security in list(context.portfolio.positions.keys()):
        order_target_value(security, 0)


def get_history(security, count):
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
