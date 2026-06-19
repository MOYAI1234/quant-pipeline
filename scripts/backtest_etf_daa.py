import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.runner import RotationBacktestRunner
from research.etf_defensive_asset_allocation import (
    DefensiveAssetAllocationConfig,
    ETFDefensiveAssetAllocationBacktestStrategy,
    backtest_diagnostics,
    load_rotation_csv,
    month_end_dates,
)


def main():
    parser = argparse.ArgumentParser(
        description='本地回测 ETF-DAA-003 防御型资产配置候选策略',
    )
    parser.add_argument('--history', required=True, help='rotation CSV 路径')
    parser.add_argument('--risk-assets', required=True, help='逗号分隔风险资产')
    parser.add_argument('--defensive-assets', required=True, help='逗号分隔防御资产')
    parser.add_argument('--canary-assets', required=True, help='逗号分隔 canary 资产')
    parser.add_argument('--initial-capital', type=float, default=100000)
    parser.add_argument('--commission-rate', type=float, default=0.0003)
    parser.add_argument('--buy-commission-rate', type=float)
    parser.add_argument('--sell-commission-rate', type=float)
    parser.add_argument('--min-commission', type=float, default=5)
    parser.add_argument('--slippage-rate', type=float, default=0.001)
    parser.add_argument('--max-volume-participation', type=float)
    parser.add_argument('--allow-partial-fills', action='store_true')
    parser.add_argument('--lookback-days', type=int, default=252)
    parser.add_argument('--min-history-days', type=int, default=253)
    parser.add_argument('--min-amount', type=float)
    parser.add_argument('--risk-holdings', type=int, default=2)
    parser.add_argument('--defensive-holdings', type=int, default=1)
    parser.add_argument('--canary-threshold', type=float, default=1.0)
    parser.add_argument('--breadth-threshold', type=float, default=0.5)
    parser.add_argument('--cash-return', type=float, default=0.0)
    args = parser.parse_args()

    history = load_rotation_csv(args.history)
    strategy = ETFDefensiveAssetAllocationBacktestStrategy(
        _parse_symbols(args.risk_assets, '--risk-assets'),
        _parse_symbols(args.defensive_assets, '--defensive-assets'),
        _parse_symbols(args.canary_assets, '--canary-assets'),
        _config(args),
        rebalance_dates=month_end_dates(history),
        execution_buffer_rate=args.slippage_rate,
    )
    runner = RotationBacktestRunner(strategy, _account_config(args))
    result = runner.run(history)
    diagnostics = backtest_diagnostics(runner.strategy)

    print(runner.render_markdown(result))
    print('')
    print('## ETF-DAA-003 因子诊断')
    print(f"- 月末评估次数: {diagnostics['evaluation_count']}")
    print(f"- 有候选次数: {diagnostics['selected_count']}")
    print(f"- 空仓信号次数: {diagnostics['empty_count']}")
    print('- 风险状态: ' + _format_counts(diagnostics['regime_counts']))
    print(
        '- 最近一次候选: '
        + (','.join(diagnostics['last_selected']) if diagnostics['last_selected'] else '[]')
    )
    print(
        '- 过滤原因: '
        + _format_counts(diagnostics['rejection_reasons'])
    )


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


def _parse_symbols(value: str, option_name: str) -> list[str]:
    symbols = [symbol.strip() for symbol in value.split(',') if symbol.strip()]
    if not symbols:
        raise ValueError(f'{option_name} 不能为空')
    return symbols


def _format_counts(counts: dict) -> str:
    if not counts:
        return '无'
    return ', '.join(
        f'{key}={value}'
        for key, value in sorted(counts.items())
    )


if __name__ == '__main__':
    main()
