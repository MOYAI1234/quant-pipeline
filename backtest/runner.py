import csv
from pathlib import Path

from execution.simulator import Simulator


class BacktestRunner:

    def __init__(self, strategy, account_config: dict = None):
        self.strategy = strategy
        self.executor = Simulator(account_config or {})
        self.equity_curve = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')

        last_quote = None
        for bar in history:
            quote = self._bar_to_quote(bar)
            last_quote = quote
            current_prices = {self.strategy.symbol: quote['price']}
            portfolio = self.executor.get_portfolio(current_prices)
            signals = self.strategy.generate_signal(quote, portfolio)

            for signal in signals:
                if self.executor.execute_order(signal):
                    self.strategy.record_trade(signal)
                    if hasattr(self.strategy, 'on_trade_confirmed'):
                        self.strategy.on_trade_confirmed(signal)
                elif hasattr(self.strategy, 'on_trade_failed'):
                    self.strategy.on_trade_failed(signal)

            portfolio = self.executor.get_portfolio(current_prices)
            self.equity_curve.append({
                'date': quote['timestamp'],
                'total_value': portfolio['total_value'],
                'pnl': portfolio['pnl'],
                'pnl_percent': portfolio['pnl_percent'],
            })

        final_portfolio = self.executor.get_portfolio({self.strategy.symbol: last_quote['price']})

        return {
            'strategy': self.strategy.name,
            'symbol': self.strategy.symbol,
            'start_date': self.equity_curve[0]['date'],
            'end_date': self.equity_curve[-1]['date'],
            'initial_capital': self.executor.initial_capital,
            'final_value': final_portfolio['total_value'],
            'total_return': (
                final_portfolio['total_value'] - self.executor.initial_capital
            ) / self.executor.initial_capital,
            'max_drawdown': self._max_drawdown(),
            'trade_count': len(self.executor.trades),
            'realized_pnl': final_portfolio['realized_pnl'],
            'portfolio': final_portfolio,
            'equity_curve': list(self.equity_curve),
        }

    def render_markdown(self, result: dict) -> str:
        lines = [
            f"# 回测报告 - {result['strategy']}",
            "",
            f"- 标的: {result['symbol']}",
            f"- 区间: {result['start_date']} 至 {result['end_date']}",
            f"- 初始资金: {result['initial_capital']:.2f}",
            f"- 期末总值: {result['final_value']:.2f}",
            f"- 总收益率: {result['total_return']:.2%}",
            f"- 最大回撤: {result['max_drawdown']:.2%}",
            f"- 交易次数: {result['trade_count']}",
            f"- 已实现盈亏: {result['realized_pnl']:.2f}",
        ]
        return "\n".join(lines)

    def _bar_to_quote(self, bar: dict) -> dict:
        price = bar.get('close', bar.get('price', 0))
        return {
            'symbol': self.strategy.symbol,
            'price': price,
            'open': bar.get('open', price),
            'high': bar.get('high', price),
            'low': bar.get('low', price),
            'pre_close': bar.get('pre_close', price),
            'volume': bar.get('volume', 0),
            'amount': bar.get('amount', 0.0),
            'timestamp': bar.get('date', bar.get('timestamp', '')),
        }

    def _max_drawdown(self) -> float:
        peak = None
        max_drawdown = 0.0
        for point in self.equity_curve:
            value = point['total_value']
            peak = value if peak is None else max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
        return max_drawdown


def load_history_csv(path: str) -> list:
    rows = []
    with Path(path).open(newline='', encoding='utf-8') as file:
        for row in csv.DictReader(file):
            rows.append({
                'date': row.get('date', ''),
                'open': _to_float(row.get('open')),
                'high': _to_float(row.get('high')),
                'low': _to_float(row.get('low')),
                'close': _to_float(row.get('close')),
                'volume': _to_int(row.get('volume')),
                'amount': _to_float(row.get('amount')),
            })
    return rows


def sample_grid_history() -> list:
    return [
        _bar('2026-01-01', 4.00, 4.05, 3.95, 4.00),
        _bar('2026-01-02', 4.00, 4.02, 3.92, 3.95),
        _bar('2026-01-03', 3.95, 4.16, 3.94, 4.15),
    ]


def _bar(date: str, open_price: float, high: float, low: float, close: float) -> dict:
    return {
        'date': date,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': 1000000,
        'amount': close * 1000000,
    }


def _to_float(value) -> float:
    if value in (None, ''):
        return 0.0
    return float(value)


def _to_int(value) -> int:
    if value in (None, ''):
        return 0
    return int(float(value))
