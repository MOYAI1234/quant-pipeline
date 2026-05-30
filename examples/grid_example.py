import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import QuantPipeline
from strategy.grid_strategy import GridStrategy


def main():
    system = QuantPipeline()

    grid = GridStrategy({
        'name': '沪深300网格',
        'symbol': '510300',
        'center_price': 4.00,
        'grid_size': 0.10,
        'grid_count': 5,
        'capital_per_grid': 10000,
        'max_position': 5,
    })
    system.add_strategy(grid)

    print("网格策略配置:")
    print(f"  中心价格: {grid.center_price}")
    print(f"  网格大小: {grid.grid_size}")
    print(f"  网格数量: {grid.grid_count}")
    print(f"  买入网格: {grid.buy_grids}")
    print(f"  卖出网格: {grid.sell_grids}")
    print()

    system.run()


if __name__ == '__main__':
    main()
