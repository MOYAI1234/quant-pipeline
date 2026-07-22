#!/usr/bin/env python3
"""Generate a provisional same-day signal for fixed stock-bond allocation."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backtest_etf_fixed_allocation import (
    load_history_range,
    run_fixed_allocation_backtest,
)


def generate_payload(
    history: list[dict],
    quotes: dict[str, dict],
    *,
    stock_symbol: str,
    bond_symbol: str,
    observed_at: str,
    official_history_date: str,
    initial_capital: float = 100000,
    stock_weight: float = 0.5,
    bond_weight: float = 0.5,
    rebalance_months: tuple[int, ...] = (3, 6, 9, 12),
    commission_rate: float = 0.0003,
    min_commission: float = 5.0,
    slippage_rate: float = 0.001,
) -> dict:
    report, _ = run_fixed_allocation_backtest(
        history,
        stock_symbol=stock_symbol,
        bond_symbol=bond_symbol,
        initial_capital=initial_capital,
        stock_weight=stock_weight,
        bond_weight=bond_weight,
        rebalance_months=rebalance_months,
        commission_rate=commission_rate,
        min_commission=min_commission,
        slippage_rate=slippage_rate,
    )
    observed_date = date.fromisoformat(observed_at[:10])
    last_history_date = date.fromisoformat(history[-1]["date"])
    due = (
        observed_date.month in rebalance_months
        and (observed_date.year, observed_date.month)
        != (last_history_date.year, last_history_date.month)
    )
    prices = {symbol: float(quotes[symbol]["price"]) for symbol in (stock_symbol, bond_symbol)}
    total_value = report.cash + sum(
        report.positions[symbol] * prices[symbol]
        for symbol in (stock_symbol, bond_symbol)
    )
    weights = {stock_symbol: stock_weight, bond_symbol: bond_weight}
    current_weights = {
        symbol: report.positions[symbol] * prices[symbol] / total_value
        if total_value > 0
        else 0
        for symbol in weights
    }
    signals = []
    if due and total_value > 0:
        for symbol, target_weight in weights.items():
            target_shares = int(total_value * target_weight / prices[symbol] / 100) * 100
            current_shares = report.positions[symbol]
            if target_shares == current_shares:
                continue
            action = "BUY" if target_shares > current_shares else "SELL"
            signals.append({
                "symbol": symbol,
                "action": action,
                "target_weight": target_weight,
                "current_weight": current_weights[symbol],
                "reason": "季度月首个交易日恢复股债固定目标权重",
            })
    return {
        "provisional": True,
        "strategy_id": "local-etf-fixed-stock-bond-50-50-quarterly",
        "strategy_name": "ETF fixed stock-bond 50/50 quarterly",
        "observed_at": observed_at,
        "official_history_date": official_history_date,
        "market_data_cutoff": observed_at,
        "state": "SIGNAL" if signals else "NO_SIGNAL",
        "signals": signals,
        "signal_summary": json.dumps(
            {
                "rebalance_due": due,
                "current_shares": report.positions,
                "current_weights": current_weights,
                "target_weights": weights,
            },
            ensure_ascii=False,
        ),
        "notes": "当天报价只生成盘中临时信号；正式前向绩效仍使用官方收盘数据。",
    }


def _parse_months(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed allocation intraday signal")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--strategy-start-date", required=True)
    parser.add_argument("--official-history-date", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--stock-weight", type=float, default=0.5)
    parser.add_argument("--bond-weight", type=float, default=0.5)
    parser.add_argument("--rebalance-months", default="3,6,9,12")
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--min-commission", type=float, default=5.0)
    parser.add_argument("--slippage-rate", type=float, default=0.001)
    args = parser.parse_args(argv)

    symbols = tuple(symbol.strip() for symbol in args.etf_pool.split(",") if symbol.strip())
    if len(symbols) != 2:
        raise ValueError("固定股债策略要求恰好两个 ETF，顺序为股票、债券")
    history = load_history_range(args.history, args.strategy_start_date, args.official_history_date)
    if not history or history[-1]["date"] != args.official_history_date:
        raise ValueError("official history must end exactly on official-history-date")
    missing_history = [symbol for symbol in symbols if symbol not in history[-1].get("symbols", {})]
    if missing_history:
        raise ValueError("official history 缺少 ETF: " + ", ".join(missing_history))
    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    missing_quotes = [symbol for symbol in symbols if symbol not in quotes]
    if missing_quotes:
        raise ValueError("quotes 缺少 ETF: " + ", ".join(missing_quotes))
    payload = generate_payload(
        history,
        {symbol: quotes[symbol] for symbol in symbols},
        stock_symbol=symbols[0],
        bond_symbol=symbols[1],
        observed_at=args.observed_at,
        official_history_date=args.official_history_date,
        initial_capital=args.initial_capital,
        stock_weight=args.stock_weight,
        bond_weight=args.bond_weight,
        rebalance_months=_parse_months(args.rebalance_months),
        commission_rate=args.commission_rate,
        min_commission=args.min_commission,
        slippage_rate=args.slippage_rate,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
