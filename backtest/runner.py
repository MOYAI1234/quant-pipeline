import copy
import csv
import math
from datetime import date, datetime
from pathlib import Path

from backtest.trading_calendar import TradingCalendar
from execution.simulator import Simulator


REQUIRED_CSV_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')
EQUITY_CURVE_CSV_FIELDS = (
    'date',
    'total_value',
    'pnl',
    'pnl_percent',
    'period_return',
    'drawdown',
)
TRADE_CSV_FIELDS = (
    'timestamp',
    'action',
    'symbol',
    'price',
    'shares',
    'amount',
    'commission',
    'entry_commission',
    'profit',
    'net_profit',
)


class BacktestRunner:

    def __init__(
        self,
        strategy,
        account_config: dict = None,
        trading_calendar: TradingCalendar | None = None,
    ):
        self._strategy_template = copy.deepcopy(strategy)
        self.strategy = copy.deepcopy(self._strategy_template)
        self._account_config = dict(account_config or {})
        self.trading_calendar = trading_calendar
        self.slippage_rate = _validate_slippage_rate(
            self._account_config.get('slippage_rate', 0.0)
        )
        self.executor = None
        self.equity_curve = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')
        _validate_history_order(history)
        _validate_history_trading_days(history, self.trading_calendar)

        self.strategy = copy.deepcopy(self._strategy_template)
        self.executor = Simulator(dict(self._account_config))
        self.equity_curve = []
        last_quote = None
        for index, bar in enumerate(history, start=1):
            quote = self._bar_to_quote(bar)
            _validate_grid_quote(quote, index)
            last_quote = quote
            current_prices = {self.strategy.symbol: quote['price']}
            portfolio = self.executor.get_portfolio(current_prices)
            signals = self._generate_signals(quote, portfolio)

            for signal in signals:
                if not self._signal_executable(signal, quote):
                    continue
                execution_signal = _apply_slippage(signal, self.slippage_rate)
                previous_trade_count = len(self.executor.trades)
                if self.executor.execute_order(execution_signal):
                    self._stamp_new_trades(previous_trade_count, quote['timestamp'])
                    self.strategy.record_trade(execution_signal)
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
        self.equity_curve = _annotate_equity_curve(
            self.equity_curve,
            self.executor.initial_capital,
        )

        drawdown_stats = _drawdown_stats(
            self.equity_curve,
            self.executor.initial_capital,
        )
        cost_stats = _trade_cost_stats(
            self.executor.trades,
            self.executor.initial_capital,
        )

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
            **drawdown_stats,
            'trade_count': len(self.executor.trades),
            **_trade_outcome_stats(self.executor.trades),
            **cost_stats,
            'slippage_rate': self.slippage_rate,
            'realized_pnl': final_portfolio['realized_pnl'],
            'portfolio': final_portfolio,
            'equity_curve': list(self.equity_curve),
            'trades': _serialize_trades(self.executor.trades),
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
            f"- 最大回撤区间: {result['max_drawdown_start']} 至 {result['max_drawdown_end']}",
            f"- 交易次数: {result['trade_count']}",
            f"- 胜率: {result['win_rate']:.2%}",
            f"- 总手续费: {result['total_commission']:.2f}",
            f"- 手续费占初始资金: {result['commission_ratio']:.4%}",
            f"- 滑点: {result['slippage_rate']:.2%}",
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

    def _stamp_new_trades(self, previous_trade_count: int, timestamp: str) -> None:
        for trade in self.executor.trades[previous_trade_count:]:
            trade['timestamp'] = timestamp


class RotationBacktestRunner:

    def __init__(
        self,
        strategy,
        account_config: dict = None,
        trading_calendar: TradingCalendar | None = None,
    ):
        self._strategy_template = copy.deepcopy(strategy)
        self.strategy = copy.deepcopy(self._strategy_template)
        self._account_config = dict(account_config or {})
        self.trading_calendar = trading_calendar
        self.slippage_rate = _validate_slippage_rate(
            self._account_config.get('slippage_rate', 0.0)
        )
        self.executor = None
        self.equity_curve = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')
        _validate_history_order(history)
        _validate_history_trading_days(history, self.trading_calendar)

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
                execution_signal = _apply_slippage(signal, self.slippage_rate)
                previous_trade_count = len(self.executor.trades)
                if self.executor.execute_order(execution_signal):
                    self._stamp_new_trades(previous_trade_count, market_data['_date'])
                    self.strategy.record_trade(execution_signal)
                    if hasattr(self.strategy, 'on_trade_confirmed'):
                        self.strategy.on_trade_confirmed(execution_signal)
                elif hasattr(self.strategy, 'on_trade_failed'):
                    self.strategy.on_trade_failed(execution_signal)

            portfolio = self.executor.get_portfolio(current_prices)
            self.equity_curve.append({
                'date': snapshot.get('date', snapshot.get('timestamp', '')),
                'total_value': portfolio['total_value'],
                'pnl': portfolio['pnl'],
                'pnl_percent': portfolio['pnl_percent'],
            })

        final_market_data = self._snapshot_to_market_data(last_snapshot)
        final_portfolio = self.executor.get_portfolio(self._current_prices(final_market_data))
        self.equity_curve = _annotate_equity_curve(
            self.equity_curve,
            self.executor.initial_capital,
        )

        drawdown_stats = _drawdown_stats(
            self.equity_curve,
            self.executor.initial_capital,
        )
        cost_stats = _trade_cost_stats(
            self.executor.trades,
            self.executor.initial_capital,
        )

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
            **drawdown_stats,
            'trade_count': len(self.executor.trades),
            **_trade_outcome_stats(self.executor.trades),
            **cost_stats,
            'slippage_rate': self.slippage_rate,
            'realized_pnl': final_portfolio['realized_pnl'],
            'portfolio': final_portfolio,
            'equity_curve': list(self.equity_curve),
            'trades': _serialize_trades(self.executor.trades),
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
            f"- 最大回撤区间: {result['max_drawdown_start']} 至 {result['max_drawdown_end']}",
            f"- 交易次数: {result['trade_count']}",
            f"- 胜率: {result['win_rate']:.2%}",
            f"- 总手续费: {result['total_commission']:.2f}",
            f"- 手续费占初始资金: {result['commission_ratio']:.4%}",
            f"- 滑点: {result['slippage_rate']:.2%}",
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

    def _stamp_new_trades(self, previous_trade_count: int, timestamp: str) -> None:
        for trade in self.executor.trades[previous_trade_count:]:
            trade['timestamp'] = timestamp


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


def write_equity_curve_csv(path: str, equity_curve: list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=EQUITY_CURVE_CSV_FIELDS)
        writer.writeheader()
        for point in equity_curve:
            writer.writerow({
                'date': point.get('date', ''),
                'total_value': point.get('total_value', 0),
                'pnl': point.get('pnl', 0),
                'pnl_percent': point.get('pnl_percent', 0),
                'period_return': point.get('period_return', 0),
                'drawdown': point.get('drawdown', 0),
            })
    return output_path


def write_trades_csv(path: str, trades: list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=TRADE_CSV_FIELDS)
        writer.writeheader()
        for trade in trades:
            writer.writerow({
                field: _csv_value(trade.get(field, ''))
                for field in TRADE_CSV_FIELDS
            })
    return output_path


def _trade_outcome_stats(trades: list) -> dict:
    closed_trades = [
        trade for trade in trades
        if trade.get('action') == 'sell' and 'profit' in trade
    ]
    winning_trades = [
        trade for trade in closed_trades
        if _trade_net_profit(trade) > 0
    ]
    closed_trade_count = len(closed_trades)
    return {
        'closed_trade_count': closed_trade_count,
        'winning_trade_count': len(winning_trades),
        'win_rate': (
            len(winning_trades) / closed_trade_count
            if closed_trade_count else 0.0
        ),
    }


def _trade_cost_stats(trades: list, initial_capital: float) -> dict:
    total_commission = sum(
        trade.get('commission', 0)
        for trade in trades
    )
    return {
        'total_commission': total_commission,
        'commission_ratio': (
            total_commission / initial_capital
            if initial_capital > 0 else 0.0
        ),
    }


def _trade_net_profit(trade: dict) -> float:
    if 'net_profit' in trade:
        return trade.get('net_profit', 0)
    return trade.get('profit', 0) - trade.get('entry_commission', 0)


def _serialize_trades(trades: list) -> list:
    return [
        {
            key: _csv_value(value)
            for key, value in trade.items()
        }
        for trade in trades
    ]


def _csv_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _annotate_equity_curve(equity_curve: list, initial_capital: float) -> list:
    annotated = []
    peak = initial_capital
    previous_value = initial_capital

    for point in equity_curve:
        value = point['total_value']
        peak = max(peak, value)
        period_return = (
            (value - previous_value) / previous_value
            if previous_value else 0.0
        )
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        annotated.append({
            **point,
            'period_return': period_return,
            'drawdown': drawdown,
        })
        previous_value = value

    return annotated


def _drawdown_stats(equity_curve: list, initial_capital: float) -> dict:
    if not equity_curve:
        return {
            'max_drawdown': 0.0,
            'max_drawdown_start': '',
            'max_drawdown_end': '',
        }

    peak = initial_capital
    peak_date = equity_curve[0]['date']
    max_drawdown = 0.0
    max_drawdown_start = peak_date
    max_drawdown_end = peak_date

    for point in equity_curve:
        value = point['total_value']
        if value >= peak:
            peak = value
            peak_date = point['date']
        if peak > 0:
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_start = peak_date
                max_drawdown_end = point['date']

    return {
        'max_drawdown': max_drawdown,
        'max_drawdown_start': max_drawdown_start,
        'max_drawdown_end': max_drawdown_end,
    }


def _apply_slippage(signal: dict, slippage_rate: float) -> dict:
    if slippage_rate == 0:
        return signal
    execution_signal = dict(signal)
    price = execution_signal.get('price', 0)
    if price <= 0:
        return execution_signal

    if execution_signal.get('action') == 'buy':
        execution_price = price * (1 + slippage_rate)
    elif execution_signal.get('action') == 'sell':
        execution_price = price * (1 - slippage_rate)
    else:
        execution_price = price

    execution_signal['price'] = execution_price
    if execution_signal.get('shares', 0) > 0:
        execution_signal['amount'] = execution_signal['shares'] * execution_price
    return execution_signal


def _validate_slippage_rate(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or value >= 1
    ):
        raise ValueError('slippage_rate 必须在 0 到 1 之间，且小于 1')
    return float(value)


def _validate_grid_quote(quote: dict, index: int) -> None:
    for field in ('price', 'open', 'high', 'low'):
        label = 'close/price' if field == 'price' else field
        _validate_finite_number(
            quote[field],
            f'history 第 {index} 条字段 {label}',
            positive=True,
        )
    for field in ('volume', 'amount'):
        _validate_finite_number(
            quote[field],
            f'history 第 {index} 条字段 {field}',
            non_negative=True,
        )

    if quote['high'] < quote['low']:
        raise ValueError(f'history 第 {index} 条 high 不能小于 low')
    if not quote['low'] <= quote['open'] <= quote['high']:
        raise ValueError(
            f'history 第 {index} 条 open 必须在 low 和 high 之间'
        )
    if not quote['low'] <= quote['price'] <= quote['high']:
        raise ValueError(
            f'history 第 {index} 条 close/price 必须在 low 和 high 之间'
        )


def _validate_finite_number(
    value: int | float,
    label: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f'{label} 必须是有限数字')
    if positive and value <= 0:
        raise ValueError(f'{label} 必须大于 0')
    if non_negative and value < 0:
        raise ValueError(f'{label} 不能小于 0')


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
    _validate_history_order(filtered)
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


def _history_date(row: dict) -> date:
    value = row.get('date', row.get('timestamp', ''))
    if not isinstance(value, str) or not value:
        raise ValueError('history 行日期必须是 YYYY-MM-DD')
    return _parse_date(value[:10], 'history 行日期')


def _validate_history_order(history: list) -> None:
    previous_time = None
    previous_value = None
    for index, row in enumerate(history, start=1):
        current_value = _history_time_value(row)
        current_time = _parse_history_time(current_value)
        if previous_time is not None:
            try:
                ordered = current_time > previous_time
            except TypeError as exc:
                raise ValueError('history 时间时区格式必须一致') from exc
            if not ordered:
                raise ValueError(
                    'history 日期必须严格递增: '
                    f'第 {index} 条 {current_value} 不晚于 '
                    f'第 {index - 1} 条 {previous_value}'
                )
        previous_time = current_time
        previous_value = current_value


def _validate_history_trading_days(
    history: list,
    trading_calendar: TradingCalendar | None,
) -> None:
    if trading_calendar is None:
        return
    for index, row in enumerate(history, start=1):
        trading_date = _history_date(row)
        if not trading_calendar.is_trading_day(trading_date):
            raise ValueError(
                f'history 第 {index} 条日期 {trading_date.isoformat()} 不是交易日'
            )


def _history_time_value(row: dict) -> str:
    value = row.get('timestamp') or row.get('date')
    if not isinstance(value, str) or not value:
        raise ValueError('history 行日期必须是 YYYY-MM-DD')
    return value


def _parse_history_time(value: str) -> datetime:
    if 'T' not in value and ' ' not in value:
        return datetime.combine(
            _parse_date(value, 'history 行日期'),
            datetime.min.time(),
        )
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('history 行时间必须是 ISO 日期或时间') from exc


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
