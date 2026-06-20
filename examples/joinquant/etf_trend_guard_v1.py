"""JoinQuant script for ETF-TREND-GUARD-004.

复制到聚宽策略编辑器运行。策略主线是权益 ETF 趋势防守：

- 每日开盘评估一次，不做日内反复交易。
- 只在权益 ETF 池内选标的；弱市时降仓或空仓，不默认买债券/黄金。
- 使用长期趋势、绝对动量、波动惩罚和组合回撤暂停来控制回撤。

本文件依赖聚宽云端 API，本地只做语法检查。
"""

import math


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    g.strategy_id = "ETF-TREND-GUARD-004"
    g.etf_pool = [
        "510300.XSHG",  # 沪深300 ETF
        "510500.XSHG",  # 中证500 ETF
        "510050.XSHG",  # 上证50 ETF
        "510880.XSHG",  # 红利 ETF
        "159915.XSHE",  # 创业板 ETF
        "159919.XSHE",  # 沪深300 ETF 深市
        "512100.XSHG",  # 中证1000 ETF
    ]
    g.market_proxy = "510300.XSHG"

    g.lookback_days = 120
    g.trend_window = 200
    g.vol_window = 60
    g.min_history_days = 220
    g.min_avg_money = 30000000
    g.max_holdings = 2
    g.max_weight_per_etf = 0.50
    g.slippage_rate = 0.001

    g.portfolio_stop_drawdown = 0.12
    g.cooldown_days = 20
    g.cooldown_left = 0
    g.high_water = 0
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

    if g.high_water <= 0:
        g.high_water = context.portfolio.total_value
    g.high_water = max(g.high_water, context.portfolio.total_value)
    portfolio_drawdown = context.portfolio.total_value / g.high_water - 1.0

    if portfolio_drawdown <= -g.portfolio_stop_drawdown:
        log.info(
            "%s portfolio stop: drawdown=%.2f%% cooldown=%s"
            % (g.strategy_id, portfolio_drawdown * 100, g.cooldown_days)
        )
        sell_all(context)
        g.cooldown_left = g.cooldown_days
        return

    if g.cooldown_left > 0:
        log.info("%s cooldown left=%s, keep cash" % (g.strategy_id, g.cooldown_left))
        sell_all(context)
        g.cooldown_left -= 1
        return

    if not market_trend_ok(g.market_proxy):
        log.info("%s market trend weak, keep cash" % g.strategy_id)
        sell_all(context)
        return

    selected = select_targets()
    log.info("%s selected targets: %s" % (g.strategy_id, selected))
    apply_targets(context, selected)


def market_trend_ok(security):
    hist = history_frame(security, g.trend_window + 1)
    if hist is None:
        return False
    close = hist["close"].dropna()
    if len(close) < g.trend_window:
        return False
    latest = float(close.iloc[-1])
    ma = float(close.iloc[-g.trend_window :].mean())
    if latest <= 0 or ma <= 0:
        return False
    return latest >= ma


def select_targets():
    factors = []
    rejections = []
    for security in g.etf_pool:
        item, reason = calculate_factor(security)
        if item is None:
            rejections.append((security, reason))
        else:
            factors.append(item)

    ranked = sorted(factors, key=lambda item: item["score"], reverse=True)
    selected = []
    for item in ranked:
        if item["momentum"] <= 0:
            rejections.append((item["security"], "non_positive_momentum"))
            continue
        if not item["above_trend"]:
            rejections.append((item["security"], "below_trend"))
            continue
        selected.append(item["security"])
        if len(selected) >= g.max_holdings:
            break

    log_diagnostics(ranked, rejections)
    return selected


def calculate_factor(security):
    tradable, reason = can_trade_detail(security)
    if not tradable:
        return None, reason

    hist = history_frame(security, g.min_history_days)
    if hist is None:
        return None, "history_error"
    if "close" not in hist or "money" not in hist:
        return None, "missing_columns"

    close = hist["close"].dropna()
    money = hist["money"].dropna()
    if len(close) < g.min_history_days or len(money) < 20:
        return None, "insufficient_history"

    avg_money = float(money.iloc[-20:].mean())
    if avg_money < g.min_avg_money:
        return None, "low_avg_money"

    latest = float(close.iloc[-1])
    lookback_base = float(close.iloc[-g.lookback_days - 1])
    trend_ma = float(close.iloc[-g.trend_window :].mean())
    if latest <= 0 or lookback_base <= 0 or trend_ma <= 0:
        return None, "invalid_price"

    momentum = latest / lookback_base - 1.0
    above_trend = latest >= trend_ma
    returns = close.pct_change().dropna()
    volatility = float(returns.iloc[-g.vol_window :].std())
    if math.isnan(volatility) or volatility <= 0:
        return None, "invalid_volatility"

    # 趋势与动量为主，波动越高扣分越多。
    score = momentum - volatility * 2.0
    return {
        "security": security,
        "momentum": momentum,
        "above_trend": above_trend,
        "volatility": volatility,
        "avg_money": avg_money,
        "score": score,
    }, None


def apply_targets(context, selected):
    current_positions = list(context.portfolio.positions.keys())
    for security in current_positions:
        if security not in selected:
            order_target_value(security, 0)

    if not selected:
        return

    target_value = context.portfolio.total_value / float(len(selected))
    target_value = min(target_value, context.portfolio.total_value * g.max_weight_per_etf)
    for security in selected:
        if can_trade(security):
            order_target_value(security, target_value)


def sell_all(context):
    for security in list(context.portfolio.positions.keys()):
        order_target_value(security, 0)


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
            "%s score=%.4f momentum=%.4f vol=%.4f trend=%s avg_money=%.2f"
            % (
                item["security"],
                item["score"],
                item["momentum"],
                item["volatility"],
                item["above_trend"],
                item["avg_money"],
            )
        )
    for security, reason in rejections:
        log.info("reject %s: %s" % (security, reason))
