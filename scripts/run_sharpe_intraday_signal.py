#!/usr/bin/env python3
"""Generate one provisional same-day signal for SHARPE ETF rotation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_multi_factor import (
    calc_sharpe_momentum,
    evaluate_multi_factor_snapshot,
)
from scripts.backtest_etf_sharpe_rotation import (
    load_history_range,
    run_sharpe_backtest,
)


def _portfolio_state(
    trades: list[dict],
    initial_capital: float,
    *,
    slippage_rate: float,
) -> tuple[float, dict[str, float]]:
    cash = initial_capital
    holdings: dict[str, float] = {}
    for trade in trades:
        symbol = str(trade["symbol"])
        if trade["action"] == "BUY":
            cash -= float(trade["amount"]) + float(trade["commission"])
            holdings[symbol] = holdings.get(symbol, 0) + float(trade["shares"])
        elif trade["action"] == "SELL":
            proceeds = float(trade["amount"]) * (1 - slippage_rate)
            cash += proceeds - float(trade["commission"])
            holdings.pop(symbol, None)
    return cash, holdings


def generate_payload(
    history: list[dict],
    quotes: dict[str, dict],
    *,
    observed_at: str,
    official_history_date: str,
    initial_capital: float = 100000,
    momentum_window: int = 60,
    volatility_window: int = 60,
    min_history_days: int = 120,
    max_holdings: int = 2,
    rebalance_step: int = 5,
    warmup_days: int = 180,
) -> dict:
    report, account, config = run_sharpe_backtest(
        history,
        initial_capital=initial_capital,
        momentum_window=momentum_window,
        volatility_window=volatility_window,
        min_history_days=min_history_days,
        max_holdings=max_holdings,
        rebalance_step=rebalance_step,
        warmup_days=warmup_days,
    )
    cash, holdings = _portfolio_state(
        report.trades,
        initial_capital,
        slippage_rate=account.slippage_rate,
    )
    day_counter = len(history) + 1
    due = day_counter >= warmup_days and (
        day_counter % rebalance_step == 0
        if warmup_days > 0
        else (day_counter - 1) % rebalance_step == 0
    )
    selected = sorted(holdings)
    rankings: list[dict] = []
    if due:
        latest = history[-1]["symbols"]
        snapshot = {"date": observed_at, "symbols": {}}
        for symbol, quote in quotes.items():
            previous = latest[symbol]
            price = float(quote["price"])
            snapshot["symbols"][symbol] = {
                "price": price,
                "close": price,
                "prices": list(previous["prices"]) + [price],
                "volume": float(quote.get("volume", 0) or 0),
                "amount": float(quote.get("amount", 0) or 0),
            }
        evaluation = evaluate_multi_factor_snapshot(
            snapshot,
            config,
            "SHARPE",
            calc_sharpe_momentum,
        )
        selected = evaluation.selected
        rankings = evaluation.rankings[:5]

    prices = {symbol: float(item["price"]) for symbol, item in quotes.items()}
    total_value = cash + sum(
        shares * prices[symbol] for symbol, shares in holdings.items()
    )
    signals = []
    if due:
        target_weight = 1 / len(selected) if selected else 0
        for symbol in sorted(set(holdings) - set(selected)):
            current_weight = (
                holdings[symbol] * prices[symbol] / total_value
                if total_value > 0
                else 0
            )
            signals.append({
                "symbol": symbol,
                "action": "SELL",
                "target_weight": 0.0,
                "current_weight": current_weight,
                "reason": "SHARPE 排名退出目标组合",
            })
        for symbol in selected:
            current_weight = (
                holdings.get(symbol, 0) * prices[symbol] / total_value
                if total_value > 0
                else 0
            )
            if symbol not in holdings:
                action = "BUY"
            elif current_weight < target_weight * 0.95:
                action = "REBALANCE"
            else:
                continue
            signals.append({
                "symbol": symbol,
                "action": action,
                "target_weight": target_weight,
                "current_weight": current_weight,
                "reason": "进入 SHARPE 正分前二并等权配置",
            })

    return {
        "provisional": True,
        "strategy_id": "local-etf-sharpe-60-60",
        "strategy_name": "ETF SHARPE 60/60 rotation",
        "observed_at": observed_at,
        "official_history_date": official_history_date,
        "market_data_cutoff": observed_at,
        "state": "SIGNAL" if signals else "NO_SIGNAL",
        "signals": signals,
        "signal_summary": json.dumps(
            {
                "day_counter": day_counter,
                "rebalance_due": due,
                "current_holdings": sorted(holdings),
                "selected": selected,
                "top_rankings": rankings,
            },
            ensure_ascii=False,
        ),
        "notes": "当天报价只生成盘中临时信号；正式前向绩效仍使用官方收盘数据。",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SHARPE rotation intraday signal")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--strategy-start-date", required=True)
    parser.add_argument("--official-history-date", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--momentum-window", type=int, default=60)
    parser.add_argument("--volatility-window", type=int, default=60)
    parser.add_argument("--min-history-days", type=int, default=120)
    parser.add_argument("--max-holdings", type=int, default=2)
    parser.add_argument("--rebalance-step", type=int, default=5)
    parser.add_argument("--warmup-days", type=int, default=180)
    args = parser.parse_args(argv)

    symbols = tuple(
        symbol.strip() for symbol in args.etf_pool.split(",") if symbol.strip()
    )
    history = load_history_range(
        args.history,
        args.strategy_start_date,
        args.official_history_date,
    )
    if not history or history[-1]["date"] != args.official_history_date:
        raise ValueError("official history must end exactly on official-history-date")
    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    missing = [symbol for symbol in symbols if symbol not in quotes]
    if missing:
        raise ValueError("quotes 缺少 ETF: " + ", ".join(missing))
    missing_history = [
        symbol for symbol in symbols if symbol not in history[-1].get("symbols", {})
    ]
    if missing_history:
        raise ValueError("official history 缺少 ETF: " + ", ".join(missing_history))
    payload = generate_payload(
        history,
        {symbol: quotes[symbol] for symbol in symbols},
        observed_at=args.observed_at,
        official_history_date=args.official_history_date,
        initial_capital=args.initial_capital,
        momentum_window=args.momentum_window,
        volatility_window=args.volatility_window,
        min_history_days=args.min_history_days,
        max_holdings=args.max_holdings,
        rebalance_step=args.rebalance_step,
        warmup_days=args.warmup_days,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
