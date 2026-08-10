#!/usr/bin/env python3
"""高频波动率因子 (Parkinson / Garman-Klass / Yang-Zhang) 的 1 年回测。

数据: scripts/fetch_etf_ohlcv_tushare.py 拉取的完整 OHLCV CSV。
引擎: 复用通用 run_backtest_for_factor + 全量 warmup + 截取评估。
对照: SHARPE(60/60, close 收益波动) + 等权基准 + 纯动量。

用法:
  python scripts/backtest_etf_hf_vol.py \
      --history data/history/etf-pool-ohlcv.csv \
      --etf-pool 159659,510300,512400,513010,515120,518880 \
      --strategy-start-date 2025-06-25 --end-date 2026-06-25 \
      --summary-output outputs/hfvol-summary.json --results-output outputs/hfvol-results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.hf_volatility_factors import (
    HfVolConfig,
    calc_hf_vol_momentum,
)
from scripts.backtest_etf_multi_factor import (
    AccountConfig,
    run_backtest_for_factor,
)
from scripts.backtest_etf_sharpe_rotation import candidate_payload
from scripts.backtest_etf_novel_factors import (
    run_equal_weight_benchmark,
    slice_report,
)


def load_ohlcv_snapshots(path: str) -> list[dict]:
    """把 OHLCV 长表转成逐日 snapshot，每只 ETF 的 bar 带累积序列。

    bar = {close, prices(串), opens, highs, lows, volume, amount}
    """
    import csv

    series: dict[str, dict[str, list]] = defaultdict(
        lambda: {"dates": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": [], "amounts": []}
    )
    order: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row["symbol"]
            if sym not in series:
                order.append(sym)
            series[sym]["dates"].append(row["date"])
            series[sym]["opens"].append(float(row["open"]))
            series[sym]["highs"].append(float(row["high"]))
            series[sym]["lows"].append(float(row["low"]))
            series[sym]["closes"].append(float(row["close"]))
            series[sym]["volumes"].append(float(row.get("volume", 0) or 0))
            series[sym]["amounts"].append(float(row.get("amount", 0) or 0))

    # 按日期聚合 snapshot（日期统一为 YYYY-MM-DD ISO 格式）
    # 用增量累积序列避免每日期 O(n) 重新切片+join（整体 O(n²)→O(n)）
    by_date: dict[str, dict] = {}
    for sym in order:
        s = series[sym]
        acc = {"prices": [], "opens": [], "highs": [], "lows": []}
        for i, d in enumerate(s["dates"]):
            iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            snapshot = by_date.setdefault(iso, {"date": iso, "symbols": {}})
            acc["prices"].append(f"{s['closes'][i]:.6f}")
            acc["opens"].append(f"{s['opens'][i]:.6f}")
            acc["highs"].append(f"{s['highs'][i]:.6f}")
            acc["lows"].append(f"{s['lows'][i]:.6f}")
            snapshot["symbols"][sym] = {
                "close": s["closes"][i],
                "prices": "|".join(acc["prices"]),
                "opens": "|".join(acc["opens"]),
                "highs": "|".join(acc["highs"]),
                "lows": "|".join(acc["lows"]),
                "volume": s["volumes"][i],
                "amount": s["amounts"][i],
            }
    return [by_date[d] for d in sorted(by_date)]


def _write_json(path: str, payload: object) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="高频波动率因子回测")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--strategy-start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--warmup-days", type=int, default=180)
    parser.add_argument("--rebalance-step", type=int, default=30)
    parser.add_argument("--max-holdings", type=int, default=2)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--results-output", required=True)
    args = parser.parse_args(argv)

    expected_symbols = tuple(
        s.strip() for s in args.etf_pool.split(",") if s.strip()
    )
    all_history = load_ohlcv_snapshots(args.history)
    if not all_history:
        raise ValueError("没有历史数据")
    missing = [s for s in expected_symbols if s not in all_history[-1]["symbols"]]
    if missing:
        raise ValueError("缺少 ETF: " + ", ".join(missing))

    eval_history = [
        s for s in all_history
        if (not args.strategy_start_date or s["date"] >= args.strategy_start_date)
        and (not args.end_date or s["date"] <= args.end_date)
    ]
    account = AccountConfig(initial_capital=args.initial_capital)
    results = []

    benchmark = run_equal_weight_benchmark(eval_history, expected_symbols, account)
    bench = {
        "name": benchmark.factor_name,
        "family": "hf_vol_rotation",
        "gate_status": "BENCHMARK",
        "annual_return": benchmark.annual_return,
        "max_drawdown": abs(benchmark.max_drawdown),
        "cash_day_ratio": benchmark.cash_days / max(1, len(benchmark.equity_curve)),
        "annual_turnover": 0.0,
        "annual_commission_ratio": 0.0,
        "total_return": benchmark.total_return,
        "sharpe_ratio": benchmark.sharpe_ratio,
        "trade_count": 0,
        "trading_days": len(benchmark.equity_curve),
    }
    print(json.dumps({"factor": "EW-BENCHMARK", **bench}, ensure_ascii=False))
    results.append(bench)

    # 三种高频估计器 + SHARPE 对照 + 纯动量
    specs = [
        ("PK", HfVolConfig(estimator="parkinson")),
        ("GK", HfVolConfig(estimator="gk")),
        ("YZ", HfVolConfig(estimator="yz")),
    ]
    for name, cfg in specs:
        full = run_backtest_for_factor(
            all_history, cfg, f"{name}-HFVOL", calc_hf_vol_momentum,
            account, rebalance_step=args.rebalance_step, warmup_days=args.warmup_days,
        )
        report = slice_report(full, args.strategy_start_date, args.end_date, account)
        cand = candidate_payload(report, account)
        cand["family"] = "hf_vol_rotation"
        results.append(cand)
        print(json.dumps(cand, ensure_ascii=False))

    # SHARPE / MOM60 / 52WH 同数据对照
    from scripts.backtest_etf_novel_factors import FACTOR_SPECS
    for name in ("SHARPE", "MOM60", "52WH"):
        cfg, calc_fn = FACTOR_SPECS[name]
        full = run_backtest_for_factor(
            all_history, cfg, f"{name}-NOVEL", calc_fn,
            account, rebalance_step=args.rebalance_step, warmup_days=args.warmup_days,
        )
        report = slice_report(full, args.strategy_start_date, args.end_date, account)
        cand = candidate_payload(report, account)
        cand["family"] = "novel_factor_rotation"
        results.append(cand)
        print(json.dumps(cand, ensure_ascii=False))

    candidates = [r for r in results if r.get("gate_status") != "BENCHMARK"]
    summary = {
        "evaluated_candidates": len(candidates),
        "best_by_drawdown": min(candidates, key=lambda r: r["max_drawdown"]),
        "best_by_annual": max(candidates, key=lambda r: r["annual_return"]),
        "benchmark": bench,
    }
    _write_json(args.results_output, results)
    _write_json(args.summary_output, summary)
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
