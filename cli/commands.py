import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.runner import BacktestRunner, load_history_csv, sample_grid_history
from main import QuantPipeline
from strategy.grid_strategy import GridStrategy
from strategy.rotation_strategy import RotationStrategy


DEFAULT_BACKTEST_SYMBOL = '510300'
DEFAULT_BACKTEST_CENTER_PRICE = 4.00
DEFAULT_BACKTEST_GRID_SIZE = 0.10
DEFAULT_BACKTEST_GRID_COUNT = 5
DEFAULT_BACKTEST_SHARES_PER_GRID = 1000
DEFAULT_BACKTEST_INITIAL_CAPITAL = 100000
DEFAULT_BACKTEST_COMMISSION_RATE = 0.0003


def cmd_start(args):
    system = QuantPipeline()

    if args.strategy == 'grid':
        strategy = GridStrategy({
            'name': '网格策略',
            'symbol': args.symbol or '510300',
            'center_price': args.center_price or 4.00,
            'grid_size': args.grid_size or 0.10,
            'grid_count': args.grid_count or 5,
            'capital_per_grid': args.capital or 10000,
        })
        system.add_strategy(strategy)
    elif args.strategy == 'rotation':
        etf_pool = args.etf_pool.split(',') if args.etf_pool else ['510300', '510500', '159915', '512100']
        strategy = RotationStrategy({
            'name': '行业轮动',
            'symbol': etf_pool[0],  # 主 symbol
            'etf_pool': etf_pool,
            'lookback': args.lookback or 20,
            'top_n': args.top_n or 2,
            'rebalance_days': args.rebalance_days or 30,
        })
        system.add_strategy(strategy)

    system.run()


def cmd_status(args):
    system = QuantPipeline()
    status = system.get_status()
    print(f"资金: {status['portfolio'].get('capital', 0):.2f}")
    print(f"持仓: {status['portfolio'].get('position_count', 0)}")
    print(f"总价值: {status['portfolio'].get('total_value', 0):.2f}")
    print(f"盈亏: {status['portfolio'].get('pnl', 0):.2f}")


def cmd_report(args):
    system = QuantPipeline()
    report = system.generate_report(args.type or 'daily')
    print(report)


def cmd_backtest(args):
    if args.strategy != 'grid':
        raise ValueError('当前最小回测仅支持 grid 策略')

    symbol = _resolve_symbol(args.symbol)
    center_price = _positive_number(
        _value_or_default(args.center_price, DEFAULT_BACKTEST_CENTER_PRICE),
        '--center-price',
    )
    grid_size = _positive_number(
        _value_or_default(args.grid_size, DEFAULT_BACKTEST_GRID_SIZE),
        '--grid-size',
    )
    grid_count = _positive_int(
        _value_or_default(args.grid_count, DEFAULT_BACKTEST_GRID_COUNT),
        '--grid-count',
    )
    shares_per_grid = _positive_int(
        _value_or_default(args.shares_per_grid, DEFAULT_BACKTEST_SHARES_PER_GRID),
        '--shares-per-grid',
    )
    max_grids = _positive_int(
        _value_or_default(args.max_grids, grid_count),
        '--max-grids',
    )
    initial_capital = _positive_number(
        _value_or_default(args.initial_capital, DEFAULT_BACKTEST_INITIAL_CAPITAL),
        '--initial-capital',
    )
    commission_rate = _non_negative_number(
        _value_or_default(args.commission_rate, DEFAULT_BACKTEST_COMMISSION_RATE),
        '--commission-rate',
    )

    strategy = GridStrategy({
        'name': '网格回测',
        'symbol': symbol,
        'center_price': center_price,
        'grid_size': grid_size,
        'grid_count': grid_count,
        'shares_per_grid': shares_per_grid,
        'max_grids': max_grids,
    })
    history = load_history_csv(args.history) if args.history else sample_grid_history()
    runner = BacktestRunner(strategy, {
        'initial_capital': initial_capital,
        'commission_rate': commission_rate,
    })
    print(runner.render_markdown(runner.run(history)))


def _resolve_symbol(symbol: str) -> str:
    resolved = symbol.strip() if symbol else DEFAULT_BACKTEST_SYMBOL
    if not resolved:
        raise ValueError('--symbol 不能为空')
    return resolved


def _value_or_default(value, default):
    return default if value is None else value


def _positive_number(value: float, option_name: str) -> float:
    if value <= 0:
        raise ValueError(f"{option_name} 必须大于 0")
    return value


def _positive_int(value: int, option_name: str) -> int:
    if value <= 0:
        raise ValueError(f"{option_name} 必须大于 0")
    return value


def _non_negative_number(value: float, option_name: str) -> float:
    if value < 0:
        raise ValueError(f"{option_name} 不能小于 0")
    return value


def main():
    parser = argparse.ArgumentParser(description='量化助手 Pipeline CLI')
    subparsers = parser.add_subparsers(dest='command')

    start_parser = subparsers.add_parser('start', help='启动策略')
    start_parser.add_argument('--strategy', default='grid', choices=['grid', 'rotation'])
    start_parser.add_argument('--symbol', type=str)
    start_parser.add_argument('--center-price', type=float)
    start_parser.add_argument('--grid-size', type=float)
    start_parser.add_argument('--grid-count', type=int)
    start_parser.add_argument('--capital', type=float)
    start_parser.add_argument('--etf-pool', type=str, help='ETF池，逗号分隔')
    start_parser.add_argument('--lookback', type=int, help='回看周期')
    start_parser.add_argument('--top-n', type=int, help='选择ETF数量')
    start_parser.add_argument('--rebalance-days', type=int, help='再平衡天数')

    status_parser = subparsers.add_parser('status', help='查看状态')

    report_parser = subparsers.add_parser('report', help='生成报告')
    report_parser.add_argument('--type', default='daily', choices=['daily', 'weekly'])

    backtest_parser = subparsers.add_parser('backtest', help='运行回测')
    backtest_parser.add_argument('--strategy', default='grid', choices=['grid'])
    backtest_parser.add_argument('--symbol', type=str, default=DEFAULT_BACKTEST_SYMBOL)
    backtest_parser.add_argument('--history', type=str, help='历史行情 CSV，字段: date,open,high,low,close,volume,amount')
    backtest_parser.add_argument('--center-price', type=float)
    backtest_parser.add_argument('--grid-size', type=float)
    backtest_parser.add_argument('--grid-count', type=int)
    backtest_parser.add_argument('--shares-per-grid', type=int)
    backtest_parser.add_argument('--max-grids', type=int)
    backtest_parser.add_argument('--initial-capital', type=float)
    backtest_parser.add_argument('--commission-rate', type=float)

    args = parser.parse_args()

    if args.command == 'start':
        cmd_start(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'report':
        cmd_report(args)
    elif args.command == 'backtest':
        try:
            cmd_backtest(args)
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
