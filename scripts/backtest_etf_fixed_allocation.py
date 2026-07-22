#!/usr/bin/env python3
"""Backtest a fixed 50/50 stock-bond allocation with quarterly rebalancing.

This is the local counterpart of the supplied JoinQuant strategy.  It opens
both ETFs on the first common trading day and rebalances on the first common
trading day of March, June, September and December.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backtest_etf_multi_factor import AccountConfig, load_snapshots_from_csv


STRATEGY_FAMILY = "fixed_stock_bond_allocation"


@dataclass(frozen=True)
class FixedAllocationReport:
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    cash_days: int
    equity_curve: list[dict]
    trades: list[dict]
    cash: float
    positions: dict[str, int]


def strategy_name(stock_weight: float, bond_weight: float) -> str:
    return f"ETF-FIXED stock={stock_weight:.2f} bond={bond_weight:.2f} quarterly"


def load_history_range(path: str, start_date: str, end_date: str) -> list[dict]:
    history = load_snapshots_from_csv(path)
    return [
        item
        for item in history
        if (not start_date or item["date"] >= start_date)
        and (not end_date or item["date"] <= end_date)
    ]


def run_fixed_allocation_backtest(
    history: list[dict],
    *,
    stock_symbol: str,
    bond_symbol: str,
    initial_capital: float = 100000,
    stock_weight: float = 0.5,
    bond_weight: float = 0.5,
    rebalance_months: tuple[int, ...] = (3, 6, 9, 12),
    commission_rate: float = 0.0003,
    min_commission: float = 5.0,
    slippage_rate: float = 0.001,
) -> tuple[FixedAllocationReport, AccountConfig]:
    if not history:
        raise ValueError("固定股债回测没有可用历史数据")
    if stock_symbol == bond_symbol:
        raise ValueError("stock_symbol 与 bond_symbol 不能相同")
    if stock_weight <= 0 or bond_weight <= 0:
        raise ValueError("目标权重必须大于 0")
    if not math.isclose(stock_weight + bond_weight, 1.0, abs_tol=1e-9):
        raise ValueError("股票与债券目标权重之和必须为 1")
    if not rebalance_months or any(month < 1 or month > 12 for month in rebalance_months):
        raise ValueError("rebalance_months 必须是 1 到 12 的月份")

    account = AccountConfig(
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        min_commission=min_commission,
        slippage_rate=slippage_rate,
    )
    weights = {stock_symbol: stock_weight, bond_symbol: bond_weight}
    cash = initial_capital
    positions = {stock_symbol: 0, bond_symbol: 0}
    trades: list[dict] = []
    equity_curve: list[dict] = []
    initialized = False
    last_quarter_month: int | None = None

    for snapshot in history:
        current_date = date.fromisoformat(snapshot["date"])
        prices = _prices(snapshot, weights)
        due = not initialized
        reason = "INITIAL"
        if initialized:
            due = (
                current_date.month in rebalance_months
                and current_date.month != last_quarter_month
            )
            reason = "QUARTERLY"
        if due:
            cash = _rebalance(
                snapshot["date"],
                prices,
                weights,
                cash,
                positions,
                trades,
                account,
                reason=reason,
            )
            if initialized:
                last_quarter_month = current_date.month
            initialized = True
        equity_curve.append(
            _equity_point(snapshot["date"], prices, cash, positions, equity_curve)
        )

    report = _build_report(
        equity_curve,
        trades,
        cash,
        positions,
        account,
    )
    return report, account


def candidate_payload(
    report: FixedAllocationReport,
    account: AccountConfig,
    *,
    stock_weight: float,
    bond_weight: float,
) -> dict:
    trading_days = max(1, len(report.equity_curve))
    years = trading_days / 252
    turnover = sum(float(item["amount"]) for item in report.trades)
    commissions = sum(float(item["commission"]) for item in report.trades)
    annual_turnover = turnover / account.initial_capital / max(years, 1 / 252)
    annual_fee_ratio = commissions / account.initial_capital / max(years, 1 / 252)
    cash_day_ratio = report.cash_days / trading_days
    structural_failure = (
        cash_day_ratio > 0.80
        or annual_turnover > 8.0
        or annual_fee_ratio > 0.005
    )
    performance_failure = report.annual_return < 0.06 or report.max_drawdown > 0.15
    gate_status = (
        "REJECT"
        if structural_failure
        else "WATCHLIST" if performance_failure else "PASS"
    )
    return {
        "name": strategy_name(stock_weight, bond_weight),
        "family": STRATEGY_FAMILY,
        "gate_status": gate_status,
        "annual_return": report.annual_return,
        "max_drawdown": report.max_drawdown,
        "cash_day_ratio": cash_day_ratio,
        "annual_turnover": annual_turnover,
        "annual_commission_ratio": annual_fee_ratio,
        "total_return": report.total_return,
        "sharpe_ratio": report.sharpe_ratio,
        "trade_count": len(report.trades),
        "trading_days": trading_days,
    }


def _prices(snapshot: dict, weights: dict[str, float]) -> dict[str, float]:
    missing = [symbol for symbol in weights if symbol not in snapshot.get("symbols", {})]
    if missing:
        raise ValueError("固定股债历史缺少 ETF: " + ", ".join(missing))
    prices = {
        symbol: float(snapshot["symbols"][symbol].get("close", 0))
        for symbol in weights
    }
    invalid = [symbol for symbol, price in prices.items() if price <= 0]
    if invalid:
        raise ValueError("固定股债价格无效: " + ", ".join(invalid))
    return prices


def _rebalance(
    trade_date: str,
    prices: dict[str, float],
    weights: dict[str, float],
    cash: float,
    positions: dict[str, int],
    trades: list[dict],
    account: AccountConfig,
    *,
    reason: str,
) -> float:
    total_value = cash + sum(positions[symbol] * prices[symbol] for symbol in weights)
    targets = {
        symbol: int(total_value * weight / prices[symbol] / 100) * 100
        for symbol, weight in weights.items()
    }
    for symbol in weights:
        shares = positions[symbol] - targets[symbol]
        if shares <= 0:
            continue
        gross = shares * prices[symbol]
        commission = max(gross * account.commission_rate, account.min_commission)
        proceeds = gross * (1 - account.slippage_rate) - commission
        positions[symbol] -= shares
        cash += proceeds
        trades.append(_trade(trade_date, "SELL", symbol, prices[symbol], shares, gross, commission, reason))
    for symbol in weights:
        shares = targets[symbol] - positions[symbol]
        if shares <= 0:
            continue
        execution_price = prices[symbol] * (1 + account.slippage_rate)
        commission = max(shares * execution_price * account.commission_rate, account.min_commission)
        affordable = int(max(0, cash - commission) / execution_price / 100) * 100
        shares = min(shares, affordable)
        if shares <= 0:
            continue
        gross = shares * prices[symbol]
        cost = shares * execution_price
        commission = max(cost * account.commission_rate, account.min_commission)
        positions[symbol] += shares
        cash -= cost + commission
        trades.append(_trade(trade_date, "BUY", symbol, prices[symbol], shares, gross, commission, reason))
    return cash


def _trade(
    trade_date: str,
    action: str,
    symbol: str,
    price: float,
    shares: int,
    amount: float,
    commission: float,
    reason: str,
) -> dict:
    return {
        "date": trade_date,
        "action": action,
        "symbol": symbol,
        "price": price,
        "shares": shares,
        "amount": amount,
        "commission": commission,
        "reason": reason,
    }


def _equity_point(
    point_date: str,
    prices: dict[str, float],
    cash: float,
    positions: dict[str, int],
    previous: list[dict],
) -> dict:
    positions_value = sum(positions[symbol] * prices[symbol] for symbol in positions)
    total_value = cash + positions_value
    previous_value = previous[-1]["total_value"] if previous else total_value
    peak = max([total_value, *(item["total_value"] for item in previous)])
    return {
        "date": point_date,
        "cash": cash,
        "positions_value": positions_value,
        "total_value": total_value,
        "period_return": (
            (total_value - previous_value) / previous_value if previous_value > 0 else 0
        ),
        "drawdown": (total_value - peak) / peak if peak > 0 else 0,
    }


def _build_report(
    equity_curve: list[dict],
    trades: list[dict],
    cash: float,
    positions: dict[str, int],
    account: AccountConfig,
) -> FixedAllocationReport:
    final_value = equity_curve[-1]["total_value"]
    years = len(equity_curve) / 252
    annual_return = (final_value / account.initial_capital) ** (1 / max(years, 0.01)) - 1
    daily_returns = [item["period_return"] for item in equity_curve]
    mean_return = sum(daily_returns) / len(daily_returns)
    variance = (
        sum((item - mean_return) ** 2 for item in daily_returns) / (len(daily_returns) - 1)
        if len(daily_returns) > 1
        else 0
    )
    sharpe = mean_return / math.sqrt(variance) * math.sqrt(252) if variance > 0 else 0
    return FixedAllocationReport(
        total_return=(final_value - account.initial_capital) / account.initial_capital,
        annual_return=annual_return,
        max_drawdown=abs(min(item["drawdown"] for item in equity_curve)),
        sharpe_ratio=sharpe,
        cash_days=sum(item["positions_value"] < 100 for item in equity_curve),
        equity_curve=equity_curve,
        trades=trades,
        cash=cash,
        positions=dict(positions),
    )


def _parse_months(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def _write_json(path: str, payload: object) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed stock-bond allocation backtest")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--strategy-start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--stock-weight", type=float, default=0.5)
    parser.add_argument("--bond-weight", type=float, default=0.5)
    parser.add_argument("--rebalance-months", default="3,6,9,12")
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--min-commission", type=float, default=5.0)
    parser.add_argument("--slippage-rate", type=float, default=0.001)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--results-output", required=True)
    args = parser.parse_args(argv)

    symbols = tuple(symbol.strip() for symbol in args.etf_pool.split(",") if symbol.strip())
    if len(symbols) != 2:
        raise ValueError("固定股债策略要求恰好两个 ETF，顺序为股票、债券")
    history = load_history_range(args.history, args.strategy_start_date, args.end_date)
    report, account = run_fixed_allocation_backtest(
        history,
        stock_symbol=symbols[0],
        bond_symbol=symbols[1],
        initial_capital=args.initial_capital,
        stock_weight=args.stock_weight,
        bond_weight=args.bond_weight,
        rebalance_months=_parse_months(args.rebalance_months),
        commission_rate=args.commission_rate,
        min_commission=args.min_commission,
        slippage_rate=args.slippage_rate,
    )
    candidate = candidate_payload(
        report,
        account,
        stock_weight=args.stock_weight,
        bond_weight=args.bond_weight,
    )
    summary = {"evaluated_candidates": 1, "best_by_drawdown": candidate, "best_by_annual": candidate}
    _write_json(args.results_output, [candidate])
    _write_json(args.summary_output, summary)
    print(json.dumps(candidate, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
