from abc import ABC, abstractmethod


class BaseStrategy(ABC):

    def __init__(self, config):
        self.config = config
        self.name = config.get('name', 'Unknown')
        self.symbol = config.get('symbol')
        self.trades = []

    @abstractmethod
    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        """生成交易信号，portfolio 为当前组合状态"""
        pass

    @abstractmethod
    def calc_position_size(self, capital: float, price: float) -> int:
        pass

    def record_trade(self, trade: dict):
        self.trades.append(trade)

    def get_performance(self) -> dict:
        if not self.trades:
            return {}
        profits = [t.get('profit', 0) for t in self.trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]
        return {
            'total_trades': len(self.trades),
            'win_rate': len(wins) / len(self.trades) if self.trades else 0,
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'total_profit': sum(profits),
            'max_loss': min(losses) if losses else 0,
        }

    def get_current_shares(self, portfolio: dict) -> int:
        """从 portfolio 获取当前持仓股数"""
        if not portfolio:
            return 0
        positions = portfolio.get('positions', {})
        if self.symbol in positions:
            return positions[self.symbol].get('shares', 0)
        return 0
