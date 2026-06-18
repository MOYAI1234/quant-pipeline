"""JoinQuant reproduction script for ETF-MOM-ROT-001.

Paste this file into the JoinQuant strategy editor. It depends on JoinQuant's
cloud strategy runtime APIs, so it is not intended to run as a local script.
The local repository only syntax-checks it.
"""

import math


def initialize(context):
    """JoinQuant strategy entrypoint."""
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)

    # ETF rotation candidate universe. Review availability in JoinQuant before
    # interpreting results, because some ETFs have shorter histories.
    g.etf_pool = [
        "510300.XSHG",  # HS300 ETF
        "510500.XSHG",  # CSI 500 ETF
        "159915.XSHE",  # ChiNext ETF
        "588000.XSHG",  # STAR 50 ETF
        "510880.XSHG",  # Dividend ETF
        "511010.XSHG",  # Treasury bond ETF
        "518880.XSHG",  # Gold ETF
    ]

    g.strategy_id = "ETF-MOM-ROT-001"
    g.lookback_days = 120
    g.momentum_window = 60
    g.confirm_window = 20
    g.vol_window = 20
    g.min_history_days = 120
    g.min_avg_money = 20000000
    g.max_holdings = 2
    g.max_weight_per_etf = 0.50
    g.stop_loss = 0.10
    g.slippage_rate = 0.001

    # ETF/fund style costs: no stamp tax, bilateral commission, pressure-test
    # minimum commission. Adjust this to match the broker account under review.
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

    run_weekly(rebalance, weekday=1, time="open")
    run_daily(check_stop_loss, time="open")


def rebalance(context):
    """Weekly rebalance using only historical bars before the current day."""
    selected = select_targets(context)
    log.info("%s selected targets: %s" % (g.strategy_id, selected))

    current_positions = list(context.portfolio.positions.keys())
    for security in current_positions:
        if security not in selected:
            log.info("sell out %s: no longer selected" % security)
            order_target_value(security, 0)

    if not selected:
        log.info("no ETF passed filters; keep cash after selling stale positions")
        return

    target_value = context.portfolio.total_value / float(len(selected))
    target_value = min(target_value, context.portfolio.total_value * g.max_weight_per_etf)

    for security in selected:
        if not can_trade(security):
            log.info("skip buy %s: not tradable" % security)
            continue
        log.info("target %s to %.2f" % (security, target_value))
        order_target_value(security, target_value)


def select_targets(context):
    """Score ETF candidates by momentum, confirmation and volatility."""
    scores = []
    for security in g.etf_pool:
        factor = calculate_factor(security)
        if factor is None:
            continue
        scores.append(factor)

    if not scores:
        return []

    # Higher momentum and confirmation are better; lower volatility is better.
    momentum_ranks = rank_values(scores, "momentum", reverse=True)
    confirm_ranks = rank_values(scores, "confirm", reverse=True)
    volatility_ranks = rank_values(scores, "volatility", reverse=False)

    ranked = []
    for item in scores:
        security = item["security"]
        score = (
            momentum_ranks[security]
            + confirm_ranks[security]
            + volatility_ranks[security]
        )
        ranked.append((score, security, item))

    ranked.sort(key=lambda row: row[0])
    selected = []
    for _, security, item in ranked:
        if item["momentum"] <= 0 or item["confirm"] <= 0:
            continue
        if can_trade(security):
            selected.append(security)
        if len(selected) >= g.max_holdings:
            break
    return selected


def calculate_factor(security):
    """Return factor dict or None if the ETF fails history/liquidity filters."""
    if not can_trade(security):
        return None

    hist = attribute_history(
        security,
        g.lookback_days + 1,
        unit="1d",
        fields=["close", "money"],
        skip_paused=True,
        df=True,
        fq="pre",
    )
    if hist is None or len(hist) < g.min_history_days:
        return None
    if "close" not in hist or "money" not in hist:
        return None

    close = hist["close"].dropna()
    money = hist["money"].dropna()
    if len(close) < g.min_history_days or len(money) < g.confirm_window:
        return None

    avg_money = float(money.iloc[-g.confirm_window :].mean())
    if avg_money < g.min_avg_money:
        return None

    latest = float(close.iloc[-1])
    momentum_base = float(close.iloc[-g.momentum_window - 1])
    confirm_base = float(close.iloc[-g.confirm_window - 1])
    if latest <= 0 or momentum_base <= 0 or confirm_base <= 0:
        return None

    momentum = latest / momentum_base - 1.0
    confirm = latest / confirm_base - 1.0
    returns = close.pct_change().dropna()
    volatility = float(returns.iloc[-g.vol_window :].std())
    if math.isnan(volatility):
        return None

    return {
        "security": security,
        "momentum": momentum,
        "confirm": confirm,
        "volatility": volatility,
        "avg_money": avg_money,
    }


def rank_values(items, key, reverse):
    ordered = sorted(items, key=lambda item: item[key], reverse=reverse)
    ranks = {}
    for index, item in enumerate(ordered):
        ranks[item["security"]] = index + 1
    return ranks


def check_stop_loss(context):
    """Daily stop-loss check based on JoinQuant position cost."""
    current_data = get_current_data()
    for security, position in context.portfolio.positions.items():
        if position.total_amount <= 0:
            continue
        if security not in current_data or current_data[security].paused:
            continue
        last_price = current_data[security].last_price
        avg_cost = position.avg_cost
        if avg_cost <= 0 or last_price is None or last_price <= 0:
            continue
        drawdown = last_price / avg_cost - 1.0
        if drawdown <= -g.stop_loss:
            log.info(
                "stop loss %s: last=%.4f avg_cost=%.4f drawdown=%.2f%%"
                % (security, last_price, avg_cost, drawdown * 100)
            )
            order_target_value(security, 0)


def can_trade(security):
    current_data = get_current_data()
    if security not in current_data:
        return False
    data = current_data[security]
    if data.paused:
        return False
    if data.last_price is None or data.last_price <= 0:
        return False
    if data.high_limit is not None and data.last_price >= data.high_limit:
        return False
    if data.low_limit is not None and data.last_price <= data.low_limit:
        return False
    return True
