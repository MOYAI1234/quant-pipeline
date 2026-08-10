#!/usr/bin/env python3
"""新因子 (52WH / ER / DDM) 的 1 年 ETF 轮动回测脚本。

复用 scripts/backtest_etf_multi_factor.py 的通用回测引擎:
  - 每 rebalance_step 个交易日调仓一次
  - 因子打分为正的 top max_holdings 只等权持有
  - 手续费 0.03% (最低 5 元)，滑点 0.1%
  - 额外输出等权买入持有基准，便于对比

用法:
  python scripts/backtest_etf_novel_factors.py \
      --history data/history/current-etf-pool-20260626.csv \
      --etf-pool 159659,510300,512400,513010,515120,518880 \
      --strategy-start-date 2025-06-25 --end-date 2026-06-25 \
      --factors 52WH,ER,DDM \
      --summary-output outputs/summary.json --results-output outputs/results.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_multi_factor import SharpeMomConfig, calc_sharpe_momentum
from research.etf_novel_factors import (
    Combined52WHIDConfig,
    DownsideDevConfig,
    EfficiencyRatioConfig,
    FiftyTwoWeekHighConfig,
    HurstConfig,
    InfoDiscretenessConfig,
    RealizedKurtConfig,
    calc_52_week_high,
    calc_52wh_idmom,
    calc_downside_dev,
    calc_efficiency_ratio,
    calc_hurst_trend,
    calc_info_discreteness,
    calc_realized_kurt,
)
from scripts.backtest_etf_multi_factor import (
    AccountConfig,
    BacktestReport,
    load_snapshots_from_csv,
    run_backtest_for_factor,
)
from scripts.backtest_etf_sharpe_rotation import candidate_payload


STRATEGY_FAMILY = "novel_factor_rotation"


def run_equal_weight_benchmark(
    history: list[dict],
    etf_pool: list[str],
    account: AccountConfig,
) -> BacktestReport:
    """等权买入持有基准：首个共同交易日等权买入池内全部 ETF，持有到期。

    无调仓、无手续费（近似），用于与轮动策略对比 alpha。
    """
    cash = account.initial_capital
    positions = {}
    equity_curve = []
    first = True

    valid_pool = [s for s in etf_pool if s in history[0].get("symbols", {})]

    for snapshot in history:
        date = snapshot["date"]
        symbols = snapshot.get("symbols", {})

        if first:
            n = max(1, len(valid_pool))
            per_position = cash / n
            for symbol in valid_pool:
                bar = symbols.get(symbol)
                if not bar:
                    continue
                price = bar.get("close") or 0
                if price <= 0:
                    continue
                shares = int(per_position / price / 100) * 100
                if shares <= 0:
                    continue
                cash -= shares * price
                positions[symbol] = {"shares": shares, "avg_price": price}
            first = False

        positions_value = 0
        for sym, pos in positions.items():
            bar = symbols.get(sym, {})
            price = bar.get("close") or 0
            positions_value += pos["shares"] * price

        total_value = cash + positions_value
        prev_value = account.initial_capital
        if equity_curve:
            prev_value = equity_curve[-1]["total_value"]
        period_return = (total_value - prev_value) / prev_value if prev_value > 0 else 0
        peak = max(p["total_value"] for p in equity_curve) if equity_curve else total_value
        peak = max(peak, total_value)
        drawdown = (total_value - peak) / peak if peak > 0 else 0

        equity_curve.append({
            "date": date,
            "cash": cash,
            "positions_value": positions_value,
            "total_value": total_value,
            "period_return": period_return,
            "drawdown": drawdown,
        })

    return _compute_performance("EW-BENCHMARK", equity_curve, [], account)


def _compute_performance(
    factor_name: str,
    equity_curve: list[dict],
    trades: list[dict],
    account: AccountConfig,
    base_value: float | None = None,
) -> BacktestReport:
    """计算绩效指标。

    base_value: 区间基准值。None 时用 initial_capital（全区间模式）；
                提供时按区间起点归一化（截取评估模式），equity_curve
                必须是截取后的区间序列。
    """
    if not equity_curve:
        return BacktestReport(
            factor_name=factor_name,
            total_return=0, annual_return=0, max_drawdown=0,
            sharpe_ratio=0, win_rate=0, trade_count=0,
            avg_holdings=0, cash_days=0, equity_curve=[], trades=[],
        )
    start_value = base_value or account.initial_capital
    final_value = equity_curve[-1]["total_value"]
    total_return = (final_value - start_value) / start_value if start_value > 0 else 0
    days = len(equity_curve)
    years = days / 252
    annual_return = (final_value / start_value) ** (1 / max(years, 0.01)) - 1 if start_value > 0 else 0

    # 区间内回撤: 以区间起点为峰值基准
    peak = start_value
    max_dd = 0.0
    for p in equity_curve:
        peak = max(peak, p["total_value"])
        dd = (p["total_value"] - peak) / peak if peak > 0 else 0
        max_dd = min(max_dd, dd)

    # 零收益日是有效观测点，不过滤；仅跳过缺失值
    daily_returns = [p["period_return"] for p in equity_curve
                     if p["period_return"] is not None and not math.isnan(p["period_return"])]

    sharpe = 0
    if daily_returns and len(daily_returns) > 1:
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_ret = math.sqrt(variance)
        if std_ret > 0:
            sharpe = (mean_ret / std_ret) * math.sqrt(252)

    sell_trades = [t for t in trades if t["action"] == "SELL"]
    wins = [t for t in sell_trades if t["profit"] > 0]
    win_rate = len(wins) / len(sell_trades) if sell_trades else 0
    positions_value_list = [p.get("positions_value", 0) for p in equity_curve]
    cash_days = sum(1 for v in positions_value_list if v < 100)

    return BacktestReport(
        factor_name=factor_name,
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        win_rate=win_rate,
        trade_count=len(trades),
        avg_holdings=0,
        cash_days=cash_days,
        equity_curve=equity_curve,
        trades=trades,
    )


def slice_report(
    report: BacktestReport,
    start_date: str,
    end_date: str,
    account: AccountConfig,
) -> BacktestReport:
    """把全区间回测报告截取到 [start_date, end_date]，按区间起点归一化。

    用于: 全量历史(含 warmup) 上跑引擎，再截取评估区间，保证
    "1 年回测" 名副其实（warmup 用区间外历史）。
    """
    curve = [p for p in report.equity_curve if start_date <= p["date"] <= end_date]
    trades = [t for t in report.trades if start_date <= t["date"] <= end_date]
    if not curve:
        return BacktestReport(
            factor_name=report.factor_name,
            total_return=0, annual_return=0, max_drawdown=0,
            sharpe_ratio=0, win_rate=0, trade_count=0,
            avg_holdings=0, cash_days=0, equity_curve=[], trades=[],
        )
    base_value = curve[0]["total_value"]
    return _compute_performance(
        report.factor_name,
        curve,
        trades,
        account,
        base_value=base_value,
    )


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


def calc_mom60(
    symbol: str,
    bar: dict,
    config,
) -> tuple[dict | None, str | None]:
    """纯 60 日动量反事实对照（factor = momentum_60d，无任何缩放）。"""
    prices = bar.get("prices", [])
    if isinstance(prices, str):
        prices = [float(p) for p in prices.split("|") if p]
    if len(prices) < 61:
        return None, f'insufficient_prices len={len(prices)} need=61'
    prices = [float(p) for p in prices]
    if any(p <= 0 for p in prices):
        return None, 'invalid_prices'
    momentum = prices[-1] / prices[-61] - 1.0
    if not math.isfinite(momentum):
        return None, 'nan_momentum'
    return {
        "symbol": symbol,
        "factor_value": momentum,
        "momentum": momentum,
        "amount": bar.get("amount"),
    }, None


FACTOR_SPECS = {
    # 第一批: 经典因子 (2026-07-31)
    "52WH": (FiftyTwoWeekHighConfig(), calc_52_week_high),
    "ER": (EfficiencyRatioConfig(), calc_efficiency_ratio),
    "DDM": (DownsideDevConfig(), calc_downside_dev),
    # 第二批: 2010s+ 现代因子 (2026-07-31)
    "IDMOM": (InfoDiscretenessConfig(), calc_info_discreteness),
    "HURST": (HurstConfig(), calc_hurst_trend),
    "RKURT": (RealizedKurtConfig(), calc_realized_kurt),
    # 组合: 52WH 选股主体 × IDMOM 信息离散度质量调节
    "52WH-ID": (Combined52WHIDConfig(), calc_52wh_idmom),
    # 已有因子做同引擎同截取对照 (SHARPE 60/60 与已验证配置一致)
    "SHARPE": (
        SharpeMomConfig(momentum_window=60, volatility_window=60, min_history_days=120),
        calc_sharpe_momentum,
    ),
    # 反事实对照: 纯 60d 动量（检验现代因子缩放是否真的贡献增量）
    "MOM60": (
        SharpeMomConfig(momentum_window=60, volatility_window=60, min_history_days=120),
        calc_mom60,
    ),
}




def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="新因子 ETF 轮动回测")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--strategy-start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--factors", default="52WH,ER,DDM")
    parser.add_argument("--max-holdings", type=int, default=2)
    parser.add_argument("--rebalance-step", type=int, default=5)
    parser.add_argument("--warmup-days", type=int, default=0,
                        help="预热交易日数(对齐基准用, 常见 180)")
    parser.add_argument("--high-threshold", type=float, default=0.0,
                        help="52WH 因子接近高点阈值 (0=恒持有, 0.85~0.92 常见)")
    parser.add_argument("--id-filter", type=float, default=0.0,
                        help="52WH-ID 组合因子: 信息离散度过滤线 (ID>此值的标的排除, 0=仅缩放不过滤)")
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--results-output", required=True)
    args = parser.parse_args(argv)

    expected_symbols = tuple(
        symbol.strip() for symbol in args.etf_pool.split(",") if symbol.strip()
    )
    # 全量历史（含 warmup 前置区间），引擎从 idx=0 全局计数 warmup
    all_history = load_snapshots_from_csv(args.history)
    if not all_history:
        raise ValueError("回测没有可用历史数据")
    missing = [s for s in expected_symbols if s not in all_history[-1].get("symbols", {})]
    if missing:
        raise ValueError("回测历史缺少 ETF: " + ", ".join(missing))

    # 评估区间内的历史（用于基准）
    eval_history = load_history_range(args.history, args.strategy_start_date, args.end_date)
    if not eval_history:
        raise ValueError("评估区间没有历史数据")

    account = AccountConfig(initial_capital=args.initial_capital)
    requested = [f.strip().upper() for f in args.factors.split(",") if f.strip()]
    unknown = [f for f in requested if f not in FACTOR_SPECS]
    if unknown:
        raise ValueError("未知因子: " + ", ".join(unknown))

    results = []
    # 基准: 在评估区间内等权买入持有（区间起点建仓）
    benchmark = run_equal_weight_benchmark(eval_history, expected_symbols, account)
    bench_summary = {
        "name": benchmark.factor_name,
        "family": STRATEGY_FAMILY,
        "gate_status": "BENCHMARK",
        "annual_return": benchmark.annual_return,
        "max_drawdown": abs(benchmark.max_drawdown),
        "cash_day_ratio": benchmark.cash_days / max(1, len(benchmark.equity_curve)),
        "annual_turnover": 0.0,
        "annual_commission_ratio": 0.0,
        "total_return": benchmark.total_return,
        "sharpe_ratio": benchmark.sharpe_ratio,
        "trade_count": benchmark.trade_count,
        "trading_days": len(benchmark.equity_curve),
    }
    print(json.dumps({"factor": "EW-BENCHMARK", **bench_summary}, ensure_ascii=False))

    for factor_name in requested:
        config, calc_fn = FACTOR_SPECS[factor_name]
        override = {"max_holdings": args.max_holdings}
        if factor_name == "52WH" and args.high_threshold > 0:
            override["high_threshold"] = args.high_threshold
        if factor_name == "52WH-ID" and args.id_filter > 0:
            override["id_filter"] = args.id_filter
        config = type(config)(**{**config.__dict__, **override})
        full_report = run_backtest_for_factor(
            all_history,
            config,
            f"{factor_name}-NOVEL",
            calc_fn,
            account,
            rebalance_step=args.rebalance_step,
            warmup_days=args.warmup_days,
        )
        report = slice_report(
            full_report, args.strategy_start_date, args.end_date, account
        )
        candidate = candidate_payload(report, account)
        candidate["family"] = STRATEGY_FAMILY
        results.append(candidate)
        print(json.dumps(candidate, ensure_ascii=False))

    results.append(bench_summary)
    candidates = [r for r in results if r.get("gate_status") != "BENCHMARK"]
    if not candidates:
        print("错误: 无有效回测候选（检查 --factors 是否为空或全部失败）")
        _write_json(args.results_output, results)
        return 1
    summary = {
        "evaluated_candidates": len(candidates),
        "best_by_drawdown": min(candidates, key=lambda r: r["max_drawdown"]),
        "best_by_annual": max(candidates, key=lambda r: r["annual_return"]),
        "benchmark": bench_summary,
    }
    _write_json(args.results_output, results)
    _write_json(args.summary_output, summary)
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
