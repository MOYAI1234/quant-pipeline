#!/usr/bin/env python3
"""Backtest the exact local counterpart of the JoinQuant SHARPE ETF rotation.

The strategy ranks ETFs by 60-day momentum divided by 60-day annualized
volatility, holds at most two positive-score ETFs equally, and rebalances on a
five-trading-day schedule after the configured warm-up period.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_multi_factor import SharpeMomConfig, calc_sharpe_momentum
from scripts.backtest_etf_multi_factor import (
    AccountConfig,
    BacktestReport,
    load_snapshots_from_csv,
    run_backtest_for_factor,
)


STRATEGY_FAMILY = "sharpe_rotation"


def strategy_name(
    *,
    momentum_window: int,
    volatility_window: int,
    rebalance_step: int,
    max_holdings: int,
    warmup_days: int,
) -> str:
    return (
        "ETF-SHARPE "
        f"momentum={momentum_window} volatility={volatility_window} "
        f"interval={rebalance_step} holdings={max_holdings} "
        f"warmup={warmup_days}"
    )


def run_sharpe_backtest(
    history: list[dict],
    *,
    initial_capital: float = 100000,
    momentum_window: int = 60,
    volatility_window: int = 60,
    min_history_days: int = 120,
    max_holdings: int = 2,
    rebalance_step: int = 5,
    warmup_days: int = 180,
) -> tuple[BacktestReport, AccountConfig, SharpeMomConfig]:
    config = SharpeMomConfig(
        momentum_window=momentum_window,
        volatility_window=volatility_window,
        min_history_days=min_history_days,
        max_holdings=max_holdings,
    )
    account = AccountConfig(initial_capital=initial_capital)
    name = strategy_name(
        momentum_window=momentum_window,
        volatility_window=volatility_window,
        rebalance_step=rebalance_step,
        max_holdings=max_holdings,
        warmup_days=warmup_days,
    )
    report = run_backtest_for_factor(
        history,
        config,
        name,
        calc_sharpe_momentum,
        account,
        rebalance_step=rebalance_step,
        warmup_days=warmup_days,
    )
    return report, account, config


def candidate_payload(
    report: BacktestReport,
    account: AccountConfig,
) -> dict:
    trading_days = max(1, len(report.equity_curve))
    years = trading_days / 252
    turnover = sum(float(item.get("amount", 0)) for item in report.trades)
    commissions = sum(float(item.get("commission", 0)) for item in report.trades)
    annual_turnover = turnover / account.initial_capital / max(years, 1 / 252)
    annual_fee_ratio = commissions / account.initial_capital / max(years, 1 / 252)
    cash_day_ratio = report.cash_days / trading_days
    max_drawdown = abs(report.max_drawdown)
    structural_failure = (
        cash_day_ratio > 0.80
        or annual_turnover > 8.0
        or annual_fee_ratio > 0.005
    )
    performance_failure = report.annual_return < 0.06 or max_drawdown > 0.15
    gate_status = (
        "REJECT"
        if structural_failure
        else "WATCHLIST" if performance_failure else "PASS"
    )
    return {
        "name": report.factor_name,
        "family": STRATEGY_FAMILY,
        "gate_status": gate_status,
        "annual_return": report.annual_return,
        "max_drawdown": max_drawdown,
        "cash_day_ratio": cash_day_ratio,
        "annual_turnover": annual_turnover,
        "annual_commission_ratio": annual_fee_ratio,
        "total_return": report.total_return,
        "sharpe_ratio": report.sharpe_ratio,
        "trade_count": report.trade_count,
        "trading_days": trading_days,
    }


def load_history_range(path: str, start_date: str, end_date: str) -> list[dict]:
    history = load_snapshots_from_csv(path)
    return [
        item
        for item in history
        if (not start_date or item["date"] >= start_date)
        and (not end_date or item["date"] <= end_date)
    ]


def _write_json(path: str, payload: object) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SHARPE ETF rotation backtest")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--strategy-start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--momentum-window", type=int, default=60)
    parser.add_argument("--volatility-window", type=int, default=60)
    parser.add_argument("--min-history-days", type=int, default=120)
    parser.add_argument("--max-holdings", type=int, default=2)
    parser.add_argument("--rebalance-step", type=int, default=5)
    parser.add_argument("--warmup-days", type=int, default=180)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--results-output", required=True)
    args = parser.parse_args(argv)

    expected_symbols = tuple(
        symbol.strip() for symbol in args.etf_pool.split(",") if symbol.strip()
    )
    history = load_history_range(
        args.history,
        args.strategy_start_date,
        args.end_date,
    )
    if not history:
        raise ValueError("SHARPE 回测没有可用历史数据")
    missing = [
        symbol
        for symbol in expected_symbols
        if symbol not in history[-1].get("symbols", {})
    ]
    if missing:
        raise ValueError("SHARPE 回测历史缺少 ETF: " + ", ".join(missing))

    report, account, _ = run_sharpe_backtest(
        history,
        initial_capital=args.initial_capital,
        momentum_window=args.momentum_window,
        volatility_window=args.volatility_window,
        min_history_days=args.min_history_days,
        max_holdings=args.max_holdings,
        rebalance_step=args.rebalance_step,
        warmup_days=args.warmup_days,
    )
    candidate = candidate_payload(report, account)
    results = [candidate]
    summary = {
        "evaluated_candidates": 1,
        "best_by_drawdown": candidate,
        "best_by_annual": candidate,
    }
    _write_json(args.results_output, results)
    _write_json(args.summary_output, summary)
    print(json.dumps(candidate, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
