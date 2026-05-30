import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import QuantPipeline
from strategy.rotation_strategy import RotationStrategy


def main():
    system = QuantPipeline()

    rotation = RotationStrategy({
        'name': '行业轮动',
        'symbol': '510300',
        'etf_pool': ['510300', '510500', '159915', '512100'],
        'lookback': 20,
        'top_n': 2,
        'rebalance_days': 30,
    })
    system.add_strategy(rotation)

    print("行业轮动策略配置:")
    print(f"  ETF池: {rotation.etf_pool}")
    print(f"  回看周期: {rotation.lookback}")
    print(f"  选择数量: {rotation.top_n}")
    print(f"  再平衡天数: {rotation.rebalance_days}")
    print()

    system.run()


if __name__ == '__main__':
    main()
