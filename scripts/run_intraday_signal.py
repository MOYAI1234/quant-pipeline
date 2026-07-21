"""Run one registered ETF trend candidate against a same-day quote snapshot.

This adapter deliberately emits provisional signal data only.  It replays the
official-history CSV through the normal backtest strategy to restore state,
then evaluates one synthetic same-day market snapshot without executing orders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.runner import RotationBacktestRunner
from research.etf_dual_momentum import load_rotation_csv
from scripts.screen_etf_trend_candidates import (
    ETFTrendCandidateStrategy,
    _candidate_configs,
    _parse_symbols,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 ETF 趋势策略盘中临时信号")
    parser.add_argument("--history", required=True)
    parser.add_argument("--etf-pool", required=True)
    parser.add_argument("--factor-family", default="all")
    parser.add_argument("--candidate-name", required=True)
    parser.add_argument("--official-history-date", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--quotes", required=True, help="JSON quote map path")
    parser.add_argument("--output", required=True)
    parser.add_argument("--initial-capital", type=float, default=100000)
    args = parser.parse_args(argv)

    etf_pool = _parse_symbols(args.etf_pool)
    history = load_rotation_csv(args.history)
    history = [item for item in history if item["date"] <= args.official_history_date]
    if not history or history[-1]["date"] != args.official_history_date:
        raise ValueError("official history must end exactly on official-history-date")
    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    if not isinstance(quotes, dict):
        raise ValueError("quotes 必须是 JSON object")
    missing = [symbol for symbol in etf_pool if symbol not in quotes]
    if missing:
        raise ValueError("quotes 缺少 ETF: " + ", ".join(missing))

    configs = _candidate_configs(etf_pool[0], args.factor_family)
    config = next((item for item in configs if item.name == args.candidate_name), None)
    if config is None:
        # Historical registry results may predate descriptive suffixes added to
        # candidate names.  Keep the persisted selection authoritative while
        # allowing a compatible current config to restore it.
        config = next(
            (
                item
                for item in configs
                if item.name.startswith(args.candidate_name + " ")
                or args.candidate_name.startswith(item.name + " ")
            ),
            None,
        )
    if config is None:
        raise ValueError("找不到 candidate-name: " + args.candidate_name)

    strategy = ETFTrendCandidateStrategy(etf_pool, config)
    runner = RotationBacktestRunner(
        strategy,
        {
            "initial_capital": args.initial_capital,
            "commission_rate": 0.0003,
            "min_commission": 0,
            "slippage_rate": 0,
            "max_volume_participation": None,
            "allow_partial_fills": True,
        },
    )
    runner.run(history)
    current_data = {"_date": args.observed_at}
    for symbol in etf_pool:
        quote = quotes[symbol]
        price = float(quote["price"])
        if price <= 0:
            raise ValueError(f"{symbol} quote price 必须大于 0")
        previous = history[-1]["symbols"][symbol]
        current_data[symbol] = {
            "price": price,
            "prices": list(previous["prices"]) + [price],
            "volume": float(quote.get("volume", 0) or 0),
            "amount": float(quote.get("amount", 0) or 0),
        }
    portfolio = runner.executor.get_portfolio(
        {symbol: current_data[symbol]["price"] for symbol in etf_pool}
    )
    signals = runner.strategy.generate_signal(current_data, portfolio)
    decision = runner.strategy.decision_history[-1] if runner.strategy.decision_history else {}
    payload = {
        "provisional": True,
        "strategy_id": "local-" + args.candidate_name,
        "strategy_name": args.candidate_name,
        "observed_at": args.observed_at,
        "official_history_date": args.official_history_date,
        "market_data_cutoff": args.observed_at,
        "state": "SIGNAL" if signals else "NO_SIGNAL",
        "signals": [
            {
                "symbol": signal.get("symbol", ""),
                "action": str(signal.get("action", "")).upper(),
                "target_weight": None,
                "current_weight": None,
                "reason": signal.get("reason", ""),
            }
            for signal in signals
        ],
        "signal_summary": json.dumps(
            {
                "decision": decision.get("decision", "no_signal"),
                "selected": decision.get("selected", []),
                "weights": decision.get("weights", {}),
                "market_strength": decision.get("market_strength"),
                "breadth": decision.get("breadth"),
            },
            ensure_ascii=False,
        ),
        "notes": "仅使用 official-history-date 前的官方日线重放状态，并追加当日最新报价；未执行订单。",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
