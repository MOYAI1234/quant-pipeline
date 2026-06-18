import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_momentum_rotation import (
    MomentumRotationConfig,
    evaluate_history,
    load_rotation_csv,
    render_json,
    render_text,
)


def main():
    parser = argparse.ArgumentParser(
        description='本地评估 ETF-MOM-ROT-001 动量轮动候选策略',
    )
    parser.add_argument('--history', required=True, help='rotation CSV 路径')
    parser.add_argument('--momentum-window', type=int, default=60)
    parser.add_argument('--confirm-window', type=int, default=20)
    parser.add_argument('--volatility-window', type=int, default=20)
    parser.add_argument('--min-history-days', type=int, default=120)
    parser.add_argument('--min-avg-amount', type=float)
    parser.add_argument('--max-holdings', type=int, default=2)
    parser.add_argument('--rebalance-step', type=int, default=5)
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args()

    config = MomentumRotationConfig(
        momentum_window=args.momentum_window,
        confirm_window=args.confirm_window,
        volatility_window=args.volatility_window,
        min_history_days=args.min_history_days,
        min_avg_amount=args.min_avg_amount,
        max_holdings=args.max_holdings,
    )
    history = load_rotation_csv(args.history)
    results = evaluate_history(
        history,
        config,
        rebalance_step=args.rebalance_step,
        limit=args.limit,
    )
    print(render_json(results) if args.json else render_text(results), end='')


if __name__ == '__main__':
    main()
