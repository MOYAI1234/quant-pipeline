import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_defensive_asset_allocation import (
    DefensiveAssetAllocationConfig,
    evaluate_history,
    load_rotation_csv,
    month_end_dates,
    render_json,
    render_text,
)


def main():
    parser = argparse.ArgumentParser(
        description='本地评估 ETF-DAA-003 防御型资产配置候选策略',
    )
    parser.add_argument('--history', required=True, help='rotation CSV 路径')
    parser.add_argument('--risk-assets', required=True, help='逗号分隔风险资产')
    parser.add_argument('--defensive-assets', required=True, help='逗号分隔防御资产')
    parser.add_argument('--canary-assets', required=True, help='逗号分隔 canary 资产')
    parser.add_argument('--lookback-days', type=int, default=252)
    parser.add_argument('--min-history-days', type=int, default=253)
    parser.add_argument('--min-amount', type=float)
    parser.add_argument('--risk-holdings', type=int, default=2)
    parser.add_argument('--defensive-holdings', type=int, default=1)
    parser.add_argument('--canary-threshold', type=float, default=1.0)
    parser.add_argument('--breadth-threshold', type=float, default=0.5)
    parser.add_argument('--cash-return', type=float, default=0.0)
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args()

    history = load_rotation_csv(args.history)
    config = _config(args)
    results = evaluate_history(
        history,
        config,
        _parse_symbols(args.risk_assets, '--risk-assets'),
        _parse_symbols(args.defensive_assets, '--defensive-assets'),
        _parse_symbols(args.canary_assets, '--canary-assets'),
        rebalance_dates=month_end_dates(history),
        limit=args.limit,
    )
    print(render_json(results) if args.json else render_text(results), end='')


def _config(args) -> DefensiveAssetAllocationConfig:
    return DefensiveAssetAllocationConfig(
        lookback_days=args.lookback_days,
        min_history_days=args.min_history_days,
        min_amount=args.min_amount,
        risk_holdings=args.risk_holdings,
        defensive_holdings=args.defensive_holdings,
        canary_threshold=args.canary_threshold,
        breadth_threshold=args.breadth_threshold,
        cash_return=args.cash_return,
    )


def _parse_symbols(value: str, option_name: str) -> list[str]:
    symbols = [symbol.strip() for symbol in value.split(',') if symbol.strip()]
    if not symbols:
        raise ValueError(f'{option_name} 不能为空')
    return symbols


if __name__ == '__main__':
    main()
