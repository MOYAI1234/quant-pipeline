import copy
import csv
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from backtest.execution_model import (
    BacktestExecutionModel,
    _apply_slippage,
    _build_volume_limits,
    _consume_signal_volume,
    _signal_shares,
    _signal_within_volume_limit,
    _validate_slippage_rate,
    _validate_volume_participation,
)
from backtest.trading_calendar import TradingCalendar
from execution.simulator import Simulator


REQUIRED_CSV_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')
ROTATION_CSV_FIELDS = ('date', 'symbol', 'close', 'prices')
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
    'requested_shares',
    'partial_fill',
    'amount',
    'commission',
    'entry_commission',
    'profit',
    'net_profit',
)
REJECTED_ORDER_CSV_FIELDS = (
    'timestamp',
    'action',
    'symbol',
    'price',
    'shares',
    'amount',
    'reason',
    'signal_reason',
)
POSITION_CSV_FIELDS = (
    'date',
    'symbol',
    'shares',
    'avg_price',
    'cost',
    'commission',
    'current_price',
    'market_value',
    'unrealized_pnl',
)
PORTFOLIO_CSV_FIELDS = (
    'date',
    'cash',
    'position_count',
    'positions_market_value',
    'total_value',
    'pnl',
    'pnl_percent',
    'realized_pnl',
    'unrealized_pnl',
    'total_value_delta',
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
        self.execution_model = BacktestExecutionModel.from_account_config(
            self._account_config
        )
        self.slippage_rate = self.execution_model.slippage_rate
        self.max_volume_participation = (
            self.execution_model.max_volume_participation
        )
        self.allow_partial_fills = self.execution_model.allow_partial_fills
        self.executor = None
        self.equity_curve = []
        self.portfolio_curve = []
        self.positions_curve = []
        self.rejected_orders = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')
        _validate_history_order(history)
        _validate_history_trading_days(history, self.trading_calendar)

        self.strategy = copy.deepcopy(self._strategy_template)
        self.executor = Simulator(dict(self._account_config))
        self.equity_curve = []
        self.portfolio_curve = []
        self.positions_curve = []
        self.rejected_orders = []
        last_quote = None
        for index, bar in enumerate(history, start=1):
            quote = self._bar_to_quote(bar)
            _validate_grid_quote(quote, index)
            last_quote = quote
            current_prices = {self.strategy.symbol: quote['price']}
            portfolio = self.executor.get_portfolio(current_prices)
            signals = self._generate_signals(quote, portfolio)
            volume_limits = self.execution_model.build_volume_limits(
                {self.strategy.symbol: quote['volume']},
            )

            for signal in signals:
                if not self._signal_executable(signal, quote):
                    continue
                decision = self.execution_model.prepare_order(
                    signal,
                    volume_limits,
                )
                execution_signal = decision.signal
                if not decision.accepted:
                    _record_rejection(
                        self.rejected_orders,
                        execution_signal,
                        quote['timestamp'],
                        decision.rejection_reason,
                    )
                    if hasattr(self.strategy, 'on_trade_failed'):
                        self.strategy.on_trade_failed(signal)
                    continue
                previous_trade_count = len(self.executor.trades)
                if self.executor.execute_order(execution_signal):
                    self.execution_model.consume_fill(
                        execution_signal,
                        volume_limits,
                    )
                    self._stamp_new_trades(
                        previous_trade_count,
                        quote['timestamp'],
                        execution_signal,
                    )
                    self.strategy.record_trade(execution_signal)
                    if hasattr(self.strategy, 'on_trade_confirmed'):
                        self.strategy.on_trade_confirmed(execution_signal)
                else:
                    _record_rejection(
                        self.rejected_orders,
                        execution_signal,
                        quote['timestamp'],
                        'executor_rejected',
                    )
                    if hasattr(self.strategy, 'on_trade_failed'):
                        self.strategy.on_trade_failed(signal)

            portfolio = self.executor.get_portfolio(current_prices)
            self.equity_curve.append({
                'date': quote['timestamp'],
                'total_value': portfolio['total_value'],
                'pnl': portfolio['pnl'],
                'pnl_percent': portfolio['pnl_percent'],
            })
            self.portfolio_curve.append(
                _serialize_portfolio_snapshot(quote['timestamp'], portfolio)
            )
            self.positions_curve.extend(
                _serialize_portfolio_positions(quote['timestamp'], portfolio)
            )

        final_portfolio = self.executor.get_portfolio({self.strategy.symbol: last_quote['price']})
        _validate_portfolio_curve_consistency(self.portfolio_curve)
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
            len(history),
        )
        viability_stats = _grid_viability_stats(
            self.strategy,
            self.executor,
            self.slippage_rate,
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
            **_rejection_stats(self.rejected_orders),
            **_trade_outcome_stats(self.executor.trades),
            **cost_stats,
            **viability_stats,
            'buy_commission_rate': self.executor.buy_commission_rate,
            'sell_commission_rate': self.executor.sell_commission_rate,
            'min_commission': self.executor.min_commission,
            'slippage_rate': self.slippage_rate,
            'max_volume_participation': self.max_volume_participation,
            'allow_partial_fills': self.allow_partial_fills,
            'realized_pnl': final_portfolio['realized_pnl'],
            'portfolio': final_portfolio,
            'equity_curve': list(self.equity_curve),
            'portfolio_curve': list(self.portfolio_curve),
            'portfolio_consistency_max_delta': (
                _portfolio_consistency_max_delta(self.portfolio_curve)
            ),
            'positions_curve': list(self.positions_curve),
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
            f"- 拒单次数: {result['rejected_order_count']}",
            _render_rejection_reasons(result['rejection_reasons']),
            f"- 胜率: {result['win_rate']:.2%}",
            f"- 总手续费: {result['total_commission']:.2f}",
            f"- 手续费占初始资金: {result['commission_ratio']:.4%}",
            f"- 总成交额: {result['total_traded_amount']:.2f}",
            f"- 成交额占初始资金: {result['turnover_ratio']:.2%}",
            f"- 每周期交易次数: {result['trades_per_period']:.4f}",
            _render_commission_drag(result['commission_to_gross_profit_ratio']),
            f"- 买入佣金率: {result['buy_commission_rate']:.4%}",
            f"- 卖出佣金率: {result['sell_commission_rate']:.4%}",
            f"- 单笔最低佣金: {result['min_commission']:.2f}",
            f"- 滑点: {result['slippage_rate']:.2%}",
            (
                "- 最小网格一轮估算成交股数: "
                f"{result['minimum_grid_round_trip_shares']}"
            ),
            (
                "- 最小网格一轮预估净收益: "
                f"{result['minimum_grid_round_trip_net_profit']:.2f}"
            ),
            _render_viability_warnings(result['viability_warnings']),
            _render_volume_participation(result['max_volume_participation']),
            _render_partial_fills(result['allow_partial_fills']),
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

    def _stamp_new_trades(
        self,
        previous_trade_count: int,
        timestamp: str,
        execution_signal: dict,
    ) -> None:
        for trade in self.executor.trades[previous_trade_count:]:
            trade['timestamp'] = timestamp
            trade['requested_shares'] = execution_signal.get(
                'requested_shares',
                trade.get('shares', 0),
            )
            trade['partial_fill'] = bool(
                execution_signal.get('partial_fill', False)
            )

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
        self.execution_model = BacktestExecutionModel.from_account_config(
            self._account_config
        )
        self.slippage_rate = self.execution_model.slippage_rate
        self.max_volume_participation = (
            self.execution_model.max_volume_participation
        )
        self.allow_partial_fills = self.execution_model.allow_partial_fills
        self.executor = None
        self.equity_curve = []
        self.portfolio_curve = []
        self.positions_curve = []
        self.rejected_orders = []

    def run(self, history: list) -> dict:
        if not history:
            raise ValueError('history 不能为空')
        _validate_history_order(history)
        _validate_history_trading_days(history, self.trading_calendar)

        self.strategy = copy.deepcopy(self._strategy_template)
        self._validate_snapshot_symbols(history)
        self.executor = Simulator(dict(self._account_config))
        self.equity_curve = []
        self.portfolio_curve = []
        self.positions_curve = []
        self.rejected_orders = []
        last_snapshot = None
        for snapshot in history:
            last_snapshot = snapshot
            market_data = self._snapshot_to_market_data(snapshot)
            current_prices = self._current_prices(market_data)
            portfolio = self.executor.get_portfolio(current_prices)
            signals = self.strategy.generate_signal(market_data, portfolio)
            volume_limits = self.execution_model.build_volume_limits(
                {
                    symbol: data.get('volume', 0)
                    for symbol, data in market_data.items()
                    if isinstance(data, dict)
                },
            )

            for signal in signals:
                decision = self.execution_model.prepare_order(
                    signal,
                    volume_limits,
                )
                execution_signal = decision.signal
                if not decision.accepted:
                    _record_rejection(
                        self.rejected_orders,
                        execution_signal,
                        market_data['_date'],
                        decision.rejection_reason,
                    )
                    if hasattr(self.strategy, 'on_trade_failed'):
                        self.strategy.on_trade_failed(execution_signal)
                    continue
                previous_trade_count = len(self.executor.trades)
                if self.executor.execute_order(execution_signal):
                    self.execution_model.consume_fill(
                        execution_signal,
                        volume_limits,
                    )
                    self._stamp_new_trades(
                        previous_trade_count,
                        market_data['_date'],
                        execution_signal,
                    )
                    self.strategy.record_trade(execution_signal)
                    if hasattr(self.strategy, 'on_trade_confirmed'):
                        self.strategy.on_trade_confirmed(execution_signal)
                else:
                    _record_rejection(
                        self.rejected_orders,
                        execution_signal,
                        market_data['_date'],
                        'executor_rejected',
                    )
                    if hasattr(self.strategy, 'on_trade_failed'):
                        self.strategy.on_trade_failed(execution_signal)

            portfolio = self.executor.get_portfolio(current_prices)
            snapshot_date = snapshot.get('date', snapshot.get('timestamp', ''))
            self.equity_curve.append({
                'date': snapshot_date,
                'total_value': portfolio['total_value'],
                'pnl': portfolio['pnl'],
                'pnl_percent': portfolio['pnl_percent'],
            })
            self.portfolio_curve.append(
                _serialize_portfolio_snapshot(snapshot_date, portfolio)
            )
            self.positions_curve.extend(
                _serialize_portfolio_positions(
                    snapshot_date,
                    portfolio,
                )
            )

        final_market_data = self._snapshot_to_market_data(last_snapshot)
        final_portfolio = self.executor.get_portfolio(self._current_prices(final_market_data))
        _validate_portfolio_curve_consistency(self.portfolio_curve)
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
            len(history),
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
            **_rejection_stats(self.rejected_orders),
            **_trade_outcome_stats(self.executor.trades),
            **cost_stats,
            'buy_commission_rate': self.executor.buy_commission_rate,
            'sell_commission_rate': self.executor.sell_commission_rate,
            'min_commission': self.executor.min_commission,
            'slippage_rate': self.slippage_rate,
            'max_volume_participation': self.max_volume_participation,
            'allow_partial_fills': self.allow_partial_fills,
            'realized_pnl': final_portfolio['realized_pnl'],
            'portfolio': final_portfolio,
            'equity_curve': list(self.equity_curve),
            'portfolio_curve': list(self.portfolio_curve),
            'portfolio_consistency_max_delta': (
                _portfolio_consistency_max_delta(self.portfolio_curve)
            ),
            'positions_curve': list(self.positions_curve),
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
            f"- 拒单次数: {result['rejected_order_count']}",
            _render_rejection_reasons(result['rejection_reasons']),
            f"- 胜率: {result['win_rate']:.2%}",
            f"- 总手续费: {result['total_commission']:.2f}",
            f"- 手续费占初始资金: {result['commission_ratio']:.4%}",
            f"- 总成交额: {result['total_traded_amount']:.2f}",
            f"- 成交额占初始资金: {result['turnover_ratio']:.2%}",
            f"- 每周期交易次数: {result['trades_per_period']:.4f}",
            _render_commission_drag(result['commission_to_gross_profit_ratio']),
            f"- 买入佣金率: {result['buy_commission_rate']:.4%}",
            f"- 卖出佣金率: {result['sell_commission_rate']:.4%}",
            f"- 单笔最低佣金: {result['min_commission']:.2f}",
            f"- 滑点: {result['slippage_rate']:.2%}",
            _render_volume_participation(result['max_volume_participation']),
            _render_partial_fills(result['allow_partial_fills']),
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
                'volume': self._snapshot_volume(symbol, bar),
            }
            if 'amount' in bar:
                market_data[symbol]['amount'] = bar['amount']
        return market_data

    def _validate_snapshot_symbols(self, history: list) -> None:
        expected_symbols = list(getattr(self.strategy, 'etf_pool', []) or [])
        for index, snapshot in enumerate(history, start=1):
            symbols = snapshot.get('symbols', {})
            if not isinstance(symbols, dict):
                raise ValueError(
                    f'rotation history 第 {index} 条 symbols 必须是对象'
                )
            missing_symbols = [
                symbol for symbol in expected_symbols
                if symbol not in symbols
            ]
            if missing_symbols:
                snapshot_time = snapshot.get(
                    'date',
                    snapshot.get('timestamp', ''),
                )
                time_suffix = f' {snapshot_time}' if snapshot_time else ''
                raise ValueError(
                    f"rotation history 第 {index} 条{time_suffix} 缺少 ETF: "
                    f"{', '.join(missing_symbols)}"
                )

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

    def _snapshot_volume(self, symbol: str, bar: dict) -> int | float:
        if self.max_volume_participation is not None:
            if 'volume' not in bar:
                raise ValueError(
                    f'rotation history 中 {symbol} 缺少 volume 字段'
                )
            volume = bar['volume']
            _validate_finite_number(
                volume,
                f'rotation history 中 {symbol} 字段 volume',
                non_negative=True,
            )
            return volume
        return bar.get('volume', 0)

    def _stamp_new_trades(
        self,
        previous_trade_count: int,
        timestamp: str,
        execution_signal: dict,
    ) -> None:
        for trade in self.executor.trades[previous_trade_count:]:
            trade['timestamp'] = timestamp
            trade['requested_shares'] = execution_signal.get(
                'requested_shares',
                trade.get('shares', 0),
            )
            trade['partial_fill'] = bool(
                execution_signal.get('partial_fill', False)
            )

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


def load_rotation_history_json(path: str) -> list:
    json_path = Path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"轮动历史 JSON 不存在: {json_path}")
    if not json_path.is_file():
        raise ValueError(f"轮动历史路径不是文件: {json_path}")

    with json_path.open(encoding='utf-8') as file:
        try:
            payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"轮动历史 JSON 格式错误: {exc.msg}") from exc

    if not isinstance(payload, list):
        raise ValueError('轮动历史 JSON 顶层必须是数组')
    if not payload:
        raise ValueError('轮动历史 JSON 不能为空')

    rows = []
    for index, snapshot in enumerate(payload, start=1):
        rows.append(_normalize_rotation_snapshot(snapshot, index))
    return rows


def load_rotation_history_csv(path: str) -> list:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"轮动历史 CSV 不存在: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"轮动历史路径不是文件: {csv_path}")

    snapshots = {}
    with csv_path.open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError('轮动历史 CSV 不能为空')

        missing = [
            field for field in ROTATION_CSV_FIELDS
            if field not in reader.fieldnames
        ]
        if missing:
            raise ValueError(f"轮动历史 CSV 缺少字段: {', '.join(missing)}")

        for line_number, row in enumerate(reader, start=2):
            if _is_blank_row(row):
                continue
            snapshot_date = _required_text(row.get('date'), 'date', line_number)
            symbol = _required_text(row.get('symbol'), 'symbol', line_number).strip()
            if not symbol:
                raise ValueError(
                    f"轮动历史 CSV 第 {line_number} 行字段 symbol 不能为空"
                )
            close = _to_float(row.get('close'), 'close', line_number)
            _validate_finite_number(
                close,
                f'轮动历史 CSV 第 {line_number} 行字段 close',
                positive=True,
            )
            bar = {
                'close': close,
                'prices': _to_price_series(row.get('prices'), line_number),
            }
            if 'volume' in reader.fieldnames and row.get('volume') not in (None, ''):
                volume = _to_float(row.get('volume'), 'volume', line_number)
                _validate_finite_number(
                    volume,
                    f'轮动历史 CSV 第 {line_number} 行字段 volume',
                    non_negative=True,
                )
                bar['volume'] = volume
            if 'amount' in reader.fieldnames and row.get('amount') not in (None, ''):
                amount = _to_float(row.get('amount'), 'amount', line_number)
                _validate_finite_number(
                    amount,
                    f'轮动历史 CSV 第 {line_number} 行字段 amount',
                    non_negative=True,
                )
                bar['amount'] = amount
            symbols = snapshots.setdefault(snapshot_date, {})
            if symbol in symbols:
                raise ValueError(
                    f'轮动历史 CSV 第 {line_number} 行重复标的: '
                    f'{snapshot_date} {symbol}'
                )
            symbols[symbol] = bar

    if not snapshots:
        raise ValueError('轮动历史 CSV 没有数据行')

    # snapshots keeps first-seen CSV date order; _validate_history_order catches disorder.
    rows = [
        _normalize_rotation_snapshot(
            {
                'date': snapshot_date,
                'symbols': symbols,
            },
            index,
        )
        for index, (snapshot_date, symbols)
        in enumerate(snapshots.items(), start=1)
    ]
    _validate_history_order(rows)
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


def write_rejected_orders_csv(path: str, rejected_orders: list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=REJECTED_ORDER_CSV_FIELDS)
        writer.writeheader()
        for order in rejected_orders:
            writer.writerow({
                field: _csv_value(order.get(field, ''))
                for field in REJECTED_ORDER_CSV_FIELDS
            })
    return output_path


def write_positions_csv(path: str, positions_curve: list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=POSITION_CSV_FIELDS)
        writer.writeheader()
        for position in positions_curve:
            writer.writerow({
                field: _csv_value(position.get(field, ''))
                for field in POSITION_CSV_FIELDS
            })
    return output_path


def write_portfolio_csv(path: str, portfolio_curve: list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=PORTFOLIO_CSV_FIELDS)
        writer.writeheader()
        for point in portfolio_curve:
            writer.writerow({
                field: _csv_value(point.get(field, ''))
                for field in PORTFOLIO_CSV_FIELDS
            })
    return output_path


def write_markdown_report(path: str, report: str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{report.rstrip()}\n", encoding='utf-8')
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


def _rejection_stats(rejected_orders: list) -> dict:
    reasons = Counter(
        order.get('reason', 'unknown')
        for order in rejected_orders
    )
    return {
        'rejected_order_count': len(rejected_orders),
        'rejection_reasons': dict(sorted(reasons.items())),
        'rejected_orders': [dict(order) for order in rejected_orders],
    }


def _record_rejection(
    rejected_orders: list,
    signal: dict,
    timestamp: str,
    reason: str,
) -> None:
    rejected_orders.append(
        _serialize_rejected_order(signal, timestamp, reason)
    )


def _serialize_rejected_order(
    signal: dict,
    timestamp: str,
    reason: str,
) -> dict:
    return {
        'timestamp': timestamp,
        'action': signal.get('action', ''),
        'symbol': signal.get('symbol', ''),
        'price': signal.get('price', 0),
        'shares': _signal_shares(signal),
        'amount': signal.get('amount', 0),
        'reason': reason,
        'signal_reason': signal.get('reason', ''),
    }


def _serialize_portfolio_snapshot(date_value: str, portfolio: dict) -> dict:
    positions = portfolio.get('positions', {})
    positions_market_value = sum(
        position.get('market_value', 0)
        for position in positions.values()
    )
    unrealized_pnl = sum(
        position.get('unrealized_pnl', 0)
        for position in positions.values()
    )
    cash = portfolio.get('capital', 0)
    total_value = portfolio.get('total_value', 0)
    return {
        'date': date_value,
        'cash': cash,
        'position_count': portfolio.get('position_count', len(positions)),
        'positions_market_value': positions_market_value,
        'total_value': total_value,
        'pnl': portfolio.get('pnl', 0),
        'pnl_percent': portfolio.get('pnl_percent', 0),
        'realized_pnl': portfolio.get('realized_pnl', 0),
        'unrealized_pnl': unrealized_pnl,
        'total_value_delta': total_value - cash - positions_market_value,
    }


def _validate_portfolio_curve_consistency(
    portfolio_curve: list,
    absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 1e-12,
) -> None:
    for index, point in enumerate(portfolio_curve, start=1):
        tolerance = _portfolio_consistency_tolerance(
            point,
            absolute_tolerance,
            relative_tolerance,
        )
        if abs(point.get('total_value_delta', 0)) > tolerance:
            raise ValueError(
                f"portfolio curve 第 {index} 条现金和持仓市值不等于总值"
            )


def _portfolio_consistency_tolerance(
    point: dict,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> float:
    # absolute covers normal ETF-scale cents; relative covers very large float balances.
    reference_value = max(
        abs(point.get('total_value', 0)),
        abs(point.get('cash', 0)) + abs(point.get('positions_market_value', 0)),
        1.0,
    )
    return max(absolute_tolerance, reference_value * relative_tolerance)


def _portfolio_consistency_max_delta(portfolio_curve: list) -> float:
    if not portfolio_curve:
        return 0.0
    return max(
        abs(point.get('total_value_delta', 0))
        for point in portfolio_curve
    )


def _serialize_portfolio_positions(date_value: str, portfolio: dict) -> list:
    positions = portfolio.get('positions', {})
    return [
        {
            'date': date_value,
            'symbol': symbol,
            'shares': position.get('shares', 0),
            'avg_price': position.get('avg_price', 0),
            'cost': position.get('cost', 0),
            'commission': position.get('commission', 0),
            'current_price': position.get('current_price', 0),
            'market_value': position.get('market_value', 0),
            'unrealized_pnl': position.get('unrealized_pnl', 0),
        }
        for symbol, position in sorted(positions.items())
    ]


def _normalize_rotation_snapshot(snapshot: dict, index: int) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError(f'轮动历史 JSON 第 {index} 条必须是对象')

    time_key = 'date' if 'date' in snapshot else 'timestamp'
    time_value = snapshot.get(time_key)
    if not isinstance(time_value, str) or not time_value:
        raise ValueError(
            f'轮动历史 JSON 第 {index} 条缺少 date/timestamp'
        )

    symbols = snapshot.get('symbols')
    if not isinstance(symbols, dict) or not symbols:
        raise ValueError(
            f'轮动历史 JSON 第 {index} 条 symbols 必须是非空对象'
        )

    normalized = {
        time_key: time_value,
        'symbols': {},
    }
    for symbol, bar in symbols.items():
        normalized_symbol = _normalize_rotation_symbol(symbol, index)
        normalized['symbols'][normalized_symbol] = _normalize_rotation_symbol_bar(
            normalized_symbol,
            bar,
            index,
        )
    return normalized


def _normalize_rotation_symbol(symbol: str, index: int) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(
            f'轮动历史 JSON 第 {index} 条 symbols 包含空标的'
        )
    return symbol.strip()


def _normalize_rotation_symbol_bar(symbol: str, bar: dict, index: int) -> dict:
    if not isinstance(bar, dict):
        raise ValueError(
            f'轮动历史 JSON 第 {index} 条 {symbol} 必须是对象'
        )

    prices = bar.get('prices')
    if not isinstance(prices, list) or not prices:
        raise ValueError(
            f'轮动历史 JSON 第 {index} 条 {symbol} prices 必须是非空数组'
        )

    normalized_prices = []
    for price_index, price in enumerate(prices, start=1):
        _validate_finite_number(
            price,
            (
                f'轮动历史 JSON 第 {index} 条 {symbol} '
                f'prices 第 {price_index} 项'
            ),
            positive=True,
        )
        normalized_prices.append(price)

    # 三层价格回退：优先 close，其次 price，最后取 prices 末项。
    close = bar.get('close', bar.get('price', normalized_prices[-1]))
    _validate_finite_number(
        close,
        f'轮动历史 JSON 第 {index} 条 {symbol} close/price',
        positive=True,
    )

    normalized = {
        'close': close,
        'prices': normalized_prices,
    }
    if 'volume' in bar:
        _validate_finite_number(
            bar['volume'],
            f'轮动历史 JSON 第 {index} 条 {symbol} volume',
            non_negative=True,
        )
        normalized['volume'] = bar['volume']
    if 'amount' in bar:
        _validate_finite_number(
            bar['amount'],
            f'轮动历史 JSON 第 {index} 条 {symbol} amount',
            non_negative=True,
        )
        normalized['amount'] = bar['amount']
    return normalized


def _render_rejection_reasons(reasons: dict) -> str:
    if not reasons:
        return '- 拒单原因: 无'
    labels = {
        'volume_limit': '成交量上限',
        'executor_rejected': '执行器拒绝',
    }
    summary = ', '.join(
        f'{labels.get(reason, reason)}={count}'
        for reason, count in reasons.items()
    )
    return f'- 拒单原因: {summary}'


def _render_commission_drag(ratio: float | None) -> str:
    if ratio is None:
        return '- 已平仓手续费/毛盈利: 不可计算（无正毛盈利）'
    return f'- 已平仓手续费/毛盈利: {ratio:.2%}'


def _render_viability_warnings(warnings: list) -> str:
    if not warnings:
        return '- 生产可行性警告: 无'
    labels = {
        'grid_round_trip_non_positive_after_costs': (
            '最小网格一轮扣除手续费和滑点后收益不为正'
        ),
        'grid_round_trip_cost_drag_high': (
            '最小网格一轮手续费和滑点侵蚀至少 50% 毛收益'
        ),
        'grid_order_below_minimum_lot': (
            '每格股数不足 100 股，模拟器无法执行整手订单'
        ),
    }
    return '- 生产可行性警告: ' + '；'.join(
        labels.get(warning, warning)
        for warning in warnings
    )


def _trade_cost_stats(
    trades: list,
    initial_capital: float,
    period_count: int = 0,
) -> dict:
    total_commission = sum(
        trade.get('commission', 0)
        for trade in trades
    )
    total_traded_amount = sum(
        trade.get('amount', 0)
        for trade in trades
    )
    closed_trades = [
        trade for trade in trades
        if trade.get('action') == 'sell' and 'profit' in trade
    ]
    closed_trade_commission = sum(
        trade.get('entry_commission', 0) + trade.get('commission', 0)
        for trade in closed_trades
    )
    gross_realized_profit = sum(
        _trade_net_profit(trade)
        + trade.get('entry_commission', 0)
        + trade.get('commission', 0)
        for trade in closed_trades
    )
    return {
        'total_commission': total_commission,
        'commission_ratio': (
            total_commission / initial_capital
            if initial_capital > 0 else 0.0
        ),
        'total_traded_amount': total_traded_amount,
        'turnover_ratio': (
            total_traded_amount / initial_capital
            if initial_capital > 0 else 0.0
        ),
        'trades_per_period': (
            len(trades) / period_count
            if period_count > 0 else 0.0
        ),
        'closed_trade_commission': closed_trade_commission,
        'gross_realized_profit': gross_realized_profit,
        'commission_to_gross_profit_ratio': (
            closed_trade_commission / gross_realized_profit
            if gross_realized_profit > 0 else None
        ),
    }


def _grid_viability_stats(strategy, executor, slippage_rate: float) -> dict:
    buy_price = strategy.center_price - strategy.grid_size
    sell_price = strategy.center_price + strategy.grid_size
    requested_shares = strategy.shares_per_grid
    shares = (requested_shares // 100) * 100
    if shares <= 0:
        return {
            'minimum_grid_round_trip_shares': 0,
            'minimum_grid_round_trip_gross_profit': 0.0,
            'minimum_grid_round_trip_estimated_cost': 0.0,
            'minimum_grid_round_trip_net_profit': 0.0,
            'minimum_grid_round_trip_cost_drag_ratio': None,
            'viability_warnings': ['grid_order_below_minimum_lot'],
        }
    buy_execution_price = _apply_slippage(
        {'action': 'buy', 'price': buy_price},
        slippage_rate,
    )['price']
    sell_execution_price = _apply_slippage(
        {'action': 'sell', 'price': sell_price},
        slippage_rate,
    )['price']
    buy_amount = buy_execution_price * shares
    sell_amount = sell_execution_price * shares
    buy_commission = max(
        buy_amount * executor.buy_commission_rate,
        executor.min_commission,
    )
    sell_commission = max(
        sell_amount * executor.sell_commission_rate,
        executor.min_commission,
    )
    gross_profit = (sell_price - buy_price) * shares
    slippage_cost = (
        (buy_execution_price - buy_price)
        + (sell_price - sell_execution_price)
    ) * shares
    estimated_cost = buy_commission + sell_commission + slippage_cost
    net_profit = gross_profit - estimated_cost
    cost_drag_ratio = (
        estimated_cost / gross_profit
        if gross_profit > 0 else None
    )
    warnings = []
    if net_profit <= 0:
        warnings.append('grid_round_trip_non_positive_after_costs')
    elif cost_drag_ratio is not None and cost_drag_ratio >= 0.5:
        warnings.append('grid_round_trip_cost_drag_high')

    return {
        'minimum_grid_round_trip_shares': shares,
        'minimum_grid_round_trip_gross_profit': gross_profit,
        'minimum_grid_round_trip_estimated_cost': estimated_cost,
        'minimum_grid_round_trip_net_profit': net_profit,
        'minimum_grid_round_trip_cost_drag_ratio': cost_drag_ratio,
        'viability_warnings': warnings,
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


def _render_volume_participation(value: float | None) -> str:
    if value is None:
        return '- 成交量参与率上限: 未启用'
    return f'- 成交量参与率上限: {value:.2%}'


def _render_partial_fills(value: bool) -> str:
    return f"- 部分成交: {'开启' if value else '关闭'}"


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
                'volume': 1000000,
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


def _to_price_series(value, line_number: int) -> list:
    if value in (None, ''):
        raise ValueError(
            f"轮动历史 CSV 第 {line_number} 行字段 prices 不能为空"
        )
    parts = [part.strip() for part in str(value).split('|')]
    if not parts:
        raise ValueError(
            f"轮动历史 CSV 第 {line_number} 行字段 prices 不能为空"
        )
    prices = []
    for index, part in enumerate(parts, start=1):
        if not part:
            raise ValueError(
                f"轮动历史 CSV 第 {line_number} 行字段 prices "
                f"第 {index} 项不能为空"
            )
        try:
            price = float(part)
        except ValueError as exc:
            raise ValueError(
                f"轮动历史 CSV 第 {line_number} 行字段 prices "
                f"第 {index} 项不是有效数字: {part}"
            ) from exc
        _validate_finite_number(
            price,
            f'轮动历史 CSV 第 {line_number} 行字段 prices 第 {index} 项',
            positive=True,
        )
        prices.append(price)
    return prices


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
