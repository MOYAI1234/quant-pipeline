import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.runner import RotationBacktestRunner
from research.etf_dual_momentum import (
    DualMomentumConfig,
    ETFDualMomentumBacktestStrategy,
    backtest_diagnostics,
    load_rotation_csv,
    month_end_dates,
)
from research.risk_pause_overlay import (
    DrawdownPauseOverlayStrategy,
    overlay_diagnostics,
)


def main():
    parser = argparse.ArgumentParser(
        description='本地回测 ETF-DUAL-MOM-002 双动量候选策略',
    )
    parser.add_argument('--history', required=True, help='rotation CSV 路径')
    parser.add_argument('--risk-assets', required=True, help='逗号分隔风险资产')
    parser.add_argument('--defensive-assets', required=True, help='逗号分隔防御资产')
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
    parser.add_argument('--risk-holdings', type=int, default=1)
    parser.add_argument('--defensive-holdings', type=int, default=1)
    parser.add_argument('--cash-return', type=float, default=0.0)
    parser.add_argument(
        '--drawdown-pause',
        type=float,
        help='组合回撤达到该比例后清仓，并暂停到下一次月末信号',
    )
    args = parser.parse_args()

    history = load_rotation_csv(args.history)
    rebalance_dates = month_end_dates(history)
    strategy = ETFDualMomentumBacktestStrategy(
        _parse_symbols(args.risk_assets, '--risk-assets'),
        _parse_symbols(args.defensive_assets, '--defensive-assets'),
        DualMomentumConfig(
            lookback_days=args.lookback_days,
            min_history_days=args.min_history_days,
            min_amount=args.min_amount,
            risk_holdings=args.risk_holdings,
            defensive_holdings=args.defensive_holdings,
            cash_return=args.cash_return,
        ),
        rebalance_dates=rebalance_dates,
        execution_buffer_rate=args.slippage_rate,
    )
    if args.drawdown_pause is not None:
        strategy = DrawdownPauseOverlayStrategy(
            strategy,
            max_drawdown=args.drawdown_pause,
            release_dates=rebalance_dates,
        )
    runner = RotationBacktestRunner(strategy, _account_config(args))
    result = runner.run(history)
    strategy_after_run = runner.strategy
    diagnostics = _strategy_diagnostics(strategy_after_run)

    print(runner.render_markdown(result))
    print('')
    print('## ETF-DUAL-MOM-002 因子诊断')
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
    if 'overlay' in diagnostics:
        overlay = diagnostics['overlay']
        print('')
        print('## 回撤暂停诊断')
        print(f"- 暂停触发次数: {overlay['pause_count']}")
        print(f"- 暂停释放次数: {overlay['release_count']}")
        print(f"- 当前仍暂停: {overlay['pause_active']}")
        print('- 暂停日期: ' + _format_pause_dates(overlay['pauses']))


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


def _strategy_diagnostics(strategy) -> dict:
    if isinstance(strategy, DrawdownPauseOverlayStrategy):
        diagnostics = backtest_diagnostics(strategy.wrapped_strategy)
        diagnostics['overlay'] = overlay_diagnostics(strategy)
        return diagnostics
    return backtest_diagnostics(strategy)


def _format_pause_dates(pauses: list) -> str:
    if not pauses:
        return '无'
    return ', '.join(
        f"{pause['date']}({pause['drawdown']:.2%})"
        for pause in pauses
    )


if __name__ == '__main__':
    main()
