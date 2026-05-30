import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import QuantPipeline
from strategy.grid_strategy import GridStrategy
from strategy.rotation_strategy import RotationStrategy


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

    status_parser = subparsers.add_parser('status', help='查看状态')

    report_parser = subparsers.add_parser('report', help='生成报告')
    report_parser.add_argument('--type', default='daily', choices=['daily', 'weekly'])

    args = parser.parse_args()

    if args.command == 'start':
        cmd_start(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'report':
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
