import copy
import csv
from datetime import date, datetime
from pathlib import Path

from execution.simulator import Simulator


REQUIRED_CSV_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')


class BacktestRunner:

    def __init__(self, strategy, account_config: dict = None):
        self._strategy_template = copy.deepcopy(strategy)
        self.strategy = copy.deepcopy(self._strategy_template)
        self._account_config = dict(account_config or {})
        self.executor = None
        self.equity_curve = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')

        self.strategy = copy.deepcopy(self._strategy_template)
        self.executor = Simulator(dict(self._account_config))
        self.equity_curve = []
        last_quote = None
        for bar in history:
            quote = self._bar_to_quote(bar)
            last_quote = quote
            current_prices = {self.strategy.symbol: quote['price']}
            portfolio = self.executor.get_portfolio(current_prices)
            signals = self._generate_signals(quote, portfolio)

            for signal in signals:
                if not self._signal_executable(signal, quote):
                    continue
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

    def _generate_signals(self, quote: dict, portfolio: dict) -> list:
        signals = []
        seen = set()
        for price in self._candidate_signal_prices(quote):
            candidate_quote = dict(quote)
            candidate_quote['price'] = price
            for signal in self.strategy.generate_signal(candidate_quote, portfolio):
                key = (
                    signal.get('action'),
                    signal.get('symbol'),
                    signal.get('price'),
                    signal.get('shares'),
                    signal.get('amount'),
                )
                if key in seen or not self._signal_executable(signal, quote):
                    continue
                seen.add(key)
                signals.append(signal)
        return signals

    def _candidate_signal_prices(self, quote: dict) -> list:
        prices = [quote['price']]
        for attr in ('buy_grids', 'sell_grids'):
            for price in getattr(self.strategy, attr, []):
                if quote['low'] <= price <= quote['high']:
                    prices.append(price)
        return prices

    def _signal_executable(self, signal: dict, quote: dict) -> bool:
        price = signal.get('price', 0)
        return quote['low'] <= price <= quote['high']

    def _max_drawdown(self) -> float:
        peak = self.executor.initial_capital
        max_drawdown = 0.0
        for point in self.equity_curve:
            value = point['total_value']
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
        return max_drawdown


class RotationBacktestRunner:

    def __init__(self, strategy, account_config: dict = None):
        self._strategy_template = copy.deepcopy(strategy)
        self.strategy = copy.deepcopy(self._strategy_template)
        self._account_config = dict(account_config or {})
        self.executor = None
        self.equity_curve = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')

        self.strategy = copy.deepcopy(self._strategy_template)
        self.executor = Simulator(dict(self._account_config))
        self.equity_curve = []
        last_snapshot = None
        for snapshot in history:
            last_snapshot = snapshot
            market_data = self._snapshot_to_market_data(snapshot)
            current_prices = self._current_prices(market_data)
            portfolio = self.executor.get_portfolio(current_prices)
            signals = self.strategy.generate_signal(market_data, portfolio)

            for signal in signals:
                if self.executor.execute_order(signal):
                    self.strategy.record_trade(signal)
                    if hasattr(self.strategy, 'on_trade_confirmed'):
                        self.strategy.on_trade_confirmed(signal)
                elif hasattr(self.strategy, 'on_trade_failed'):
                    self.strategy.on_trade_failed(signal)

            portfolio = self.executor.get_portfolio(current_prices)
            self.equity_curve.append({
                'date': snapshot.get('date', snapshot.get('timestamp', '')),
                'total_value': portfolio['total_value'],
                'pnl': portfolio['pnl'],
                'pnl_percent': portfolio['pnl_percent'],
            })

        final_market_data = self._snapshot_to_market_data(last_snapshot)
        final_portfolio = self.executor.get_portfolio(self._current_prices(final_market_data))

        return {
            'strategy': self.strategy.name,
            'symbol': ','.join(self.strategy.etf_pool),
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
            f"- 标的池: {result['symbol']}",
            f"- 区间: {result['start_date']} 至 {result['end_date']}",
            f"- 初始资金: {result['initial_capital']:.2f}",
            f"- 期末总值: {result['final_value']:.2f}",
            f"- 总收益率: {result['total_return']:.2%}",
            f"- 最大回撤: {result['max_drawdown']:.2%}",
            f"- 交易次数: {result['trade_count']}",
            f"- 已实现盈亏: {result['realized_pnl']:.2f}",
        ]
        return "\n".join(lines)

    def _snapshot_to_market_data(self, snapshot: dict) -> dict:
        symbols = snapshot.get('symbols', {})
        if not symbols:
            raise ValueError('rotation history 缺少 symbols 数据')
        market_data = {
            '_date': snapshot.get('date', snapshot.get('timestamp', '')),
        }
        for symbol, bar in symbols.items():
            market_data[symbol] = {
                'price': self._required_snapshot_price(symbol, bar),
                'prices': list(bar.get('prices', [])),
            }
        return market_data

    def _current_prices(self, market_data: dict) -> dict:
        return {
            symbol: data['price']
            for symbol, data in market_data.items()
            if isinstance(data, dict) and data.get('price', 0) > 0
        }

    def _required_snapshot_price(self, symbol: str, bar: dict) -> float:
        price = bar.get('close', bar.get('price'))
        if price is None or price <= 0:
            raise ValueError(f"rotation history 中 {symbol} 缺少有效价格")
        return price

    def _max_drawdown(self) -> float:
        peak = self.executor.initial_capital
        max_drawdown = 0.0
        for point in self.equity_curve:
            value = point['total_value']
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
        return max_drawdown


def load_history_csv(path: str) -> list:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"历史行情 CSV 不存在: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"历史行情路径不是文件: {csv_path}")

    rows = []
    with csv_path.open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError('历史行情 CSV 不能为空')

        missing = [field for field in REQUIRED_CSV_FIELDS if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"历史行情 CSV 缺少字段: {', '.join(missing)}")

        for line_number, row in enumerate(reader, start=2):
            if _is_blank_row(row):
                continue
            rows.append({
                'date': _required_text(row.get('date'), 'date', line_number),
                'open': _to_float(row.get('open'), 'open', line_number),
                'high': _to_float(row.get('high'), 'high', line_number),
                'low': _to_float(row.get('low'), 'low', line_number),
                'close': _to_float(row.get('close'), 'close', line_number),
                'volume': _to_int(row.get('volume'), 'volume', line_number),
                'amount': _to_float(row.get('amount'), 'amount', line_number),
            })
    if not rows:
        raise ValueError('历史行情 CSV 没有数据行')
    return rows


def filter_history_by_date(
    history: list,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    start_date = _validate_date_bound(start_date, '--start-date')
    end_date = _validate_date_bound(end_date, '--end-date')
    if start_date and end_date and start_date > end_date:
        raise ValueError('--start-date 不能晚于 --end-date')

    filtered = [
        row for row in history
        if _date_in_range(_history_date(row), start_date, end_date)
    ]
    if not filtered:
        raise ValueError('指定日期区间内没有历史行情')
    return filtered


def sample_grid_history() -> list:
    return [
        _bar('2026-01-01', 4.00, 4.05, 3.95, 4.00),
        _bar('2026-01-02', 4.00, 4.02, 3.88, 3.95),
        _bar('2026-01-03', 3.95, 4.16, 3.94, 4.15),
    ]


def sample_rotation_history() -> list:
    return [
        _rotation_snapshot('2026-01-01', {
            '510300': [10.0, 11.0, 12.0],
            '510500': [10.0, 9.5, 9.0],
            '159915': [10.0, 10.0, 10.5],
        }),
        _rotation_snapshot('2026-01-02', {
            '510300': [11.0, 12.0, 11.0],
            '510500': [9.0, 10.0, 12.0],
            '159915': [10.0, 10.5, 10.2],
        }),
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


def _rotation_snapshot(date: str, prices_by_symbol: dict) -> dict:
    return {
        'date': date,
        'symbols': {
            symbol: {
                'close': prices[-1],
                'prices': prices,
            }
            for symbol, prices in prices_by_symbol.items()
        },
    }


def _is_blank_row(row: dict) -> bool:
    return all(value in (None, '') for value in row.values())


def _history_date(row: dict) -> str:
    value = row.get('date', row.get('timestamp', ''))
    if not isinstance(value, str) or not value:
        raise ValueError('history 行日期必须是 YYYY-MM-DD')
    return _parse_date(value[:10], 'history 行日期')


def _date_in_range(
    history_date: date,
    start_date: str | None,
    end_date: str | None,
) -> bool:
    start = _parse_date(start_date, '--start-date') if start_date else None
    end = _parse_date(end_date, '--end-date') if end_date else None
    if start and history_date < start:
        return False
    if end and history_date > end:
        return False
    return True


def _validate_date_bound(value: str | None, option_name: str) -> str | None:
    if value is None:
        return None
    if (
        len(value) != 10
        or value[4] != '-'
        or value[7] != '-'
    ):
        raise ValueError(f'{option_name} 必须是 YYYY-MM-DD')
    _parse_date(value, option_name)
    return value


def _parse_date(value: str, label: str) -> date:
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValueError(f'{label} 必须是 YYYY-MM-DD') from exc


def _required_text(value, field: str, line_number: int) -> str:
    if value in (None, ''):
        raise ValueError(f"历史行情 CSV 第 {line_number} 行字段 {field} 不能为空")
    return value


def _to_float(value, field: str, line_number: int) -> float:
    if value in (None, ''):
        raise ValueError(f"历史行情 CSV 第 {line_number} 行字段 {field} 不能为空")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(
            f"历史行情 CSV 第 {line_number} 行字段 {field} 不是有效数字: {value}"
        ) from exc


def _to_int(value, field: str, line_number: int) -> int:
    if value in (None, ''):
        raise ValueError(f"历史行情 CSV 第 {line_number} 行字段 {field} 不能为空")
    try:
        number = float(value)
        if not number.is_integer():
            raise ValueError
        return int(number)
    except ValueError as exc:
        raise ValueError(
            f"历史行情 CSV 第 {line_number} 行字段 {field} 不是有效整数: {value}"
        ) from exc
