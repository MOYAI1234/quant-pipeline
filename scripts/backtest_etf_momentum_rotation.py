import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.runner import RotationBacktestRunner
from research.etf_momentum_rotation import (
    ETFMomentumRotationBacktestStrategy,
    MomentumRotationConfig,
    backtest_diagnostics,
    load_rotation_csv,
)


def main():
    parser = argparse.ArgumentParser(
        description='本地回测 ETF-MOM-ROT-001 动量轮动候选策略',
    )
    parser.add_argument('--history', required=True, help='rotation CSV 路径')
    parser.add_argument(
        '--etf-pool',
        default='',
        help='逗号分隔 ETF 池；默认使用 CSV 内首次出现的全部标的',
    )
    parser.add_argument('--initial-capital', type=float, default=100000)
    parser.add_argument('--commission-rate', type=float, default=0.0003)
    parser.add_argument('--buy-commission-rate', type=float)
    parser.add_argument('--sell-commission-rate', type=float)
    parser.add_argument('--min-commission', type=float, default=5)
    parser.add_argument('--slippage-rate', type=float, default=0.001)
    parser.add_argument('--max-volume-participation', type=float)
    parser.add_argument('--allow-partial-fills', action='store_true')
    parser.add_argument('--momentum-window', type=int, default=60)
    parser.add_argument('--confirm-window', type=int, default=20)
    parser.add_argument('--volatility-window', type=int, default=20)
    parser.add_argument('--min-history-days', type=int, default=120)
    parser.add_argument('--min-avg-amount', type=float)
    parser.add_argument('--max-holdings', type=int, default=2)
    parser.add_argument('--rebalance-step', type=int, default=5)
    args = parser.parse_args()

    history = load_rotation_csv(args.history)
    etf_pool = _resolve_etf_pool(args.etf_pool, history)
    strategy = ETFMomentumRotationBacktestStrategy(
        etf_pool,
        MomentumRotationConfig(
            momentum_window=args.momentum_window,
            confirm_window=args.confirm_window,
            volatility_window=args.volatility_window,
            min_history_days=args.min_history_days,
            min_avg_amount=args.min_avg_amount,
            max_holdings=args.max_holdings,
        ),
        rebalance_step=args.rebalance_step,
    )
    runner = RotationBacktestRunner(strategy, _account_config(args))
    result = runner.run(history)
    diagnostics = backtest_diagnostics(runner.strategy)

    print(runner.render_markdown(result))
    print('')
    print('## ETF-MOM-ROT-001 因子诊断')
    print(f"- 调仓评估次数: {diagnostics['evaluation_count']}")
    print(f"- 有候选次数: {diagnostics['selected_count']}")
    print(f"- 空仓信号次数: {diagnostics['empty_count']}")
    print(
        '- 最近一次候选: '
        + (','.join(diagnostics['last_selected']) if diagnostics['last_selected'] else '[]')
    )
    print(
        '- 过滤原因: '
        + _format_rejection_reasons(diagnostics['rejection_reasons'])
    )


def _account_config(args) -> dict:
    return {
        'initial_capital': args.initial_capital,
        'commission_rate': args.commission_rate,
        'buy_commission_rate': args.buy_commission_rate,
        'sell_commission_rate': args.sell_commission_rate,
        'min_commission': args.min_commission,
        'slippage_rate': args.slippage_rate,
        'max_volume_participation': args.max_volume_participation,
        'allow_partial_fills': args.allow_partial_fills,
    }


def _resolve_etf_pool(value: str, history: list) -> list:
    if value:
        symbols = [symbol.strip() for symbol in value.split(',') if symbol.strip()]
        if symbols:
            return symbols
    return list(history[0]['symbols'].keys())


def _format_rejection_reasons(reasons: dict) -> str:
    if not reasons:
        return '无'
    return ', '.join(
        f'{reason}={count}'
        for reason, count in sorted(reasons.items())
    )


if __name__ == '__main__':
    main()
