import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from strategy.base import BaseStrategy


@dataclass(frozen=True)
class MomentumRotationConfig:
    momentum_window: int = 60
    confirm_window: int = 20
    volatility_window: int = 20
    min_history_days: int = 120
    min_avg_amount: float | None = None
    max_holdings: int = 2

    @property
    def required_prices(self) -> int:
        return max(
            self.momentum_window + 1,
            self.confirm_window + 1,
            self.volatility_window + 1,
            self.min_history_days,
        )


class ETFMomentumRotationBacktestStrategy(BaseStrategy):
    """ETF-MOM-ROT-001 的本地回测适配层。"""

    def __init__(
        self,
        etf_pool: list[str],
        factor_config: MomentumRotationConfig | None = None,
        *,
        rebalance_step: int = 5,
        name: str = 'ETF-MOM-ROT-001 本地回测',
    ):
        if rebalance_step <= 0:
            raise ValueError('rebalance_step 必须大于 0')
        normalized_pool = [symbol.strip() for symbol in etf_pool if symbol.strip()]
        if not normalized_pool:
            raise ValueError('etf_pool 不能为空')

        super().__init__({
            'name': name,
            'symbol': normalized_pool[0],
            'etf_pool': normalized_pool,
        })
        self.etf_pool = normalized_pool
        self.factor_config = factor_config or MomentumRotationConfig()
        self.rebalance_step = rebalance_step
        self.selected_etfs = []
        self.evaluation_count = 0
        self.selected_history = []
        self.rejection_reasons = Counter()
        self.last_evaluation = None
        self._snapshot_count = 0

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        self._snapshot_count += 1
        if (self._snapshot_count - 1) % self.rebalance_step != 0:
            return []

        snapshot = _market_data_to_snapshot(data, self.etf_pool)
        evaluation = evaluate_snapshot(snapshot, self.factor_config)
        self.evaluation_count += 1
        self.last_evaluation = evaluation
        self.selected_etfs = list(evaluation['selected'])
        self.selected_history.append({
            'date': evaluation['date'],
            'selected': list(evaluation['selected']),
        })
        self.rejection_reasons.update(
            _base_rejection_reason(rejection['reason'])
            for rejection in evaluation['rejections']
        )
        return self._rebalance_signals(data, portfolio, self.selected_etfs)

    def calc_position_size(self, capital: float, price: float) -> int:
        if price <= 0 or not self.selected_etfs:
            return 0
        return int((capital / len(self.selected_etfs)) / price / 100) * 100

    def _rebalance_signals(
        self,
        data: dict,
        portfolio: dict | None,
        selected: list[str],
    ) -> list:
        signals = []
        positions = (portfolio or {}).get('positions', {})
        signal_time = data.get('_date') if isinstance(data, dict) else None
        costs = self._trading_costs(portfolio)

        for symbol, position in positions.items():
            if symbol in selected or position.get('shares', 0) <= 0:
                continue
            price = self._price_for(symbol, data, position)
            if price <= 0:
                continue
            shares = int(position['shares'] // 100) * 100
            if shares <= 0:
                continue
            signals.append({
                'action': 'sell',
                'symbol': symbol,
                'price': price,
                'shares': shares,
                'amount': shares * price,
                'reason': 'ETF-MOM-ROT-001 调仓卖出',
                'timestamp': signal_time,
            })

        if not selected:
            return signals

        total_value = (portfolio or {}).get('total_value', 0)
        target_value = total_value / len(selected) if total_value > 0 else 0
        available_capital = (portfolio or {}).get('capital', 0) + sum(
            self._net_sell_proceeds(signal['amount'], costs)
            for signal in signals
            if signal.get('action') == 'sell'
        )

        for symbol in selected:
            if symbol not in data:
                continue
            price = data[symbol].get('price', 0)
            if price <= 0:
                continue
            current_value = (
                positions.get(symbol, {}).get('market_value')
                or positions.get(symbol, {}).get('shares', 0) * price
            )
            budget = target_value - current_value
            if budget <= 0:
                continue
            budget = min(budget, available_capital)
            shares = self._affordable_buy_shares(budget, price, costs)
            if shares <= 0:
                continue
            amount = shares * price
            signals.append({
                'action': 'buy',
                'symbol': symbol,
                'price': price,
                'shares': shares,
                'amount': amount,
                'reason': 'ETF-MOM-ROT-001 调仓买入',
                'timestamp': signal_time,
            })
            available_capital = max(
                available_capital - self._gross_buy_cost(amount, costs),
                0,
            )

        return signals

    def _price_for(self, symbol: str, data: dict, position: dict) -> float:
        if isinstance(data.get(symbol), dict):
            price = data[symbol].get('price', 0)
            if price > 0:
                return price
        return position.get('current_price', position.get('avg_price', 0))

    def _trading_costs(self, portfolio: dict | None) -> dict:
        costs = (portfolio or {}).get('trading_costs', {})
        return {
            'buy_commission_rate': costs.get('buy_commission_rate', 0),
            'sell_commission_rate': costs.get('sell_commission_rate', 0),
            'min_commission': costs.get('min_commission', 0),
        }

    def _net_sell_proceeds(self, amount: float, costs: dict) -> float:
        commission = max(
            amount * costs['sell_commission_rate'],
            costs['min_commission'],
        )
        return max(amount - commission, 0)

    def _gross_buy_cost(self, amount: float, costs: dict) -> float:
        return amount + max(
            amount * costs['buy_commission_rate'],
            costs['min_commission'],
        )

    def _affordable_buy_shares(
        self,
        budget: float,
        price: float,
        costs: dict,
    ) -> int:
        if budget <= 0 or price <= 0:
            return 0
        max_notional = min(
            budget / (1 + costs['buy_commission_rate']),
            budget - costs['min_commission'],
        )
        if max_notional <= 0:
            return 0
        return int(max_notional / price / 100) * 100


def load_rotation_csv(path: str) -> list:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"rotation CSV 不存在: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"rotation CSV 路径不是文件: {csv_path}")

    snapshots = {}
    with csv_path.open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError('rotation CSV 不能为空')
        for field in ('date', 'symbol', 'close', 'prices'):
            if field not in reader.fieldnames:
                raise ValueError(f'rotation CSV 缺少字段: {field}')

        for line_number, row in enumerate(reader, start=2):
            if _is_blank_row(row):
                continue
            date = _required_text(row, 'date', line_number)
            symbol = _required_text(row, 'symbol', line_number).strip()
            prices = _parse_prices(row.get('prices'), line_number)
            bar = {
                'close': _required_float(row, 'close', line_number),
                'prices': prices,
            }
            if 'volume' in reader.fieldnames and row.get('volume') not in (None, ''):
                bar['volume'] = _non_negative_float(row, 'volume', line_number)
            if 'amount' in reader.fieldnames and row.get('amount') not in (None, ''):
                bar['amount'] = _non_negative_float(row, 'amount', line_number)

            symbols = snapshots.setdefault(date, {})
            if symbol in symbols:
                raise ValueError(f'rotation CSV 第 {line_number} 行重复: {date} {symbol}')
            symbols[symbol] = bar

    if not snapshots:
        raise ValueError('rotation CSV 没有数据行')

    return [
        {'date': date, 'symbols': symbols}
        for date, symbols in snapshots.items()
    ]


def evaluate_history(
    history: list,
    config: MomentumRotationConfig,
    *,
    rebalance_step: int = 5,
    limit: int | None = None,
) -> list:
    if rebalance_step <= 0:
        raise ValueError('rebalance_step 必须大于 0')
    results = []
    for index, snapshot in enumerate(history):
        if index % rebalance_step != 0:
            continue
        results.append(evaluate_snapshot(snapshot, config))
        if limit is not None and len(results) >= limit:
            break
    return results


def evaluate_snapshot(snapshot: dict, config: MomentumRotationConfig) -> dict:
    date = snapshot.get('date', snapshot.get('timestamp', ''))
    symbols = snapshot.get('symbols') or {}
    factors = []
    rejections = []
    for symbol, bar in symbols.items():
        factor, reason = calculate_factor(symbol, bar, config)
        if factor is None:
            rejections.append({'symbol': symbol, 'reason': reason})
        else:
            factors.append(factor)

    ranked = rank_factors(factors)
    selected = []
    final_rejections = []
    for item in ranked:
        symbol = item['symbol']
        if item['momentum'] <= 0:
            final_rejections.append({
                'symbol': symbol,
                'reason': 'non_positive_60d_momentum',
                'factor': item,
            })
            continue
        if item['confirm'] <= 0:
            final_rejections.append({
                'symbol': symbol,
                'reason': 'non_positive_20d_confirm',
                'factor': item,
            })
            continue
        if len(selected) >= config.max_holdings:
            final_rejections.append({
                'symbol': symbol,
                'reason': 'capacity_limit',
                'factor': item,
            })
            continue
        selected.append(symbol)

    return {
        'date': date,
        'selected': selected,
        'ranked': ranked,
        'rejections': final_rejections + rejections,
    }


def backtest_diagnostics(strategy: ETFMomentumRotationBacktestStrategy) -> dict:
    selected_count = sum(
        1 for item in strategy.selected_history
        if item['selected']
    )
    return {
        'evaluation_count': strategy.evaluation_count,
        'selected_count': selected_count,
        'empty_count': strategy.evaluation_count - selected_count,
        'last_selected': (
            strategy.selected_history[-1]['selected']
            if strategy.selected_history else []
        ),
        'rejection_reasons': dict(strategy.rejection_reasons),
    }


def calculate_factor(
    symbol: str,
    bar: dict,
    config: MomentumRotationConfig,
) -> tuple[dict | None, str | None]:
    prices = bar.get('prices') or []
    if len(prices) < config.required_prices:
        return None, f'insufficient_history len={len(prices)} need={config.required_prices}'

    try:
        prices = [float(price) for price in prices]
    except (TypeError, ValueError):
        return None, 'invalid_prices'
    if any(price <= 0 or not math.isfinite(price) for price in prices):
        return None, 'invalid_prices'

    amount = bar.get('amount')
    if config.min_avg_amount is not None and amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return None, 'invalid_amount'
        if amount < config.min_avg_amount:
            return None, 'low_amount amount=%.2f need=%.2f' % (
                amount,
                config.min_avg_amount,
            )

    latest = prices[-1]
    momentum_base = prices[-config.momentum_window - 1]
    confirm_base = prices[-config.confirm_window - 1]
    momentum = latest / momentum_base - 1.0
    confirm = latest / confirm_base - 1.0
    returns = _pct_returns(prices[-config.volatility_window - 1:])
    volatility = _stddev(returns)
    if volatility is None:
        return None, 'nan_volatility'

    return {
        'symbol': symbol,
        'momentum': momentum,
        'confirm': confirm,
        'volatility': volatility,
        'amount': amount,
    }, None


def rank_factors(factors: list) -> list:
    if not factors:
        return []
    momentum_ranks = _rank(factors, 'momentum', reverse=True)
    confirm_ranks = _rank(factors, 'confirm', reverse=True)
    volatility_ranks = _rank(factors, 'volatility', reverse=False)

    ranked = []
    for factor in factors:
        symbol = factor['symbol']
        ranked.append({
            **factor,
            'score': (
                momentum_ranks[symbol]
                + confirm_ranks[symbol]
                + volatility_ranks[symbol]
            ),
        })
    return sorted(ranked, key=lambda item: item['score'])


def render_text(results: list) -> str:
    lines = []
    for result in results:
        lines.append(f"date={result['date']}")
        selected = ','.join(result['selected']) if result['selected'] else '[]'
        lines.append(f"selected={selected}")
        if result['ranked']:
            lines.append('ranked:')
            for item in result['ranked']:
                lines.append(
                    "- {symbol} score={score} momentum={momentum:.4f} "
                    "confirm={confirm:.4f} volatility={volatility:.4f}".format(
                        **item
                    )
                )
        if result['rejections']:
            lines.append('rejections:')
            for rejection in result['rejections']:
                factor = rejection.get('factor')
                suffix = ''
                if factor:
                    suffix = (
                        " momentum={momentum:.4f} confirm={confirm:.4f} "
                        "volatility={volatility:.4f}"
                    ).format(**factor)
                lines.append(
                    f"- {rejection['symbol']}: {rejection['reason']}{suffix}"
                )
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def render_json(results: list) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2) + '\n'


def _rank(factors: list, key: str, *, reverse: bool) -> dict:
    ordered = sorted(factors, key=lambda item: item[key], reverse=reverse)
    return {
        item['symbol']: index + 1
        for index, item in enumerate(ordered)
    }


def _market_data_to_snapshot(data: dict, etf_pool: list[str]) -> dict:
    return {
        'date': data.get('_date', data.get('date', data.get('timestamp', ''))),
        'symbols': {
            symbol: _market_data_symbol_bar(data[symbol])
            for symbol in etf_pool
            if isinstance(data.get(symbol), dict)
        },
    }


def _market_data_symbol_bar(bar: dict) -> dict:
    snapshot_bar = {
        'close': bar.get('close', bar.get('price')),
        'prices': list(bar.get('prices', [])),
    }
    if 'volume' in bar:
        snapshot_bar['volume'] = bar['volume']
    if 'amount' in bar:
        snapshot_bar['amount'] = bar['amount']
    return snapshot_bar


def _base_rejection_reason(reason: str) -> str:
    return reason.split()[0] if reason else 'unknown'


def _pct_returns(prices: list) -> list:
    returns = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0:
            return []
        returns.append(current / previous - 1.0)
    return returns


def _stddev(values: list) -> float | None:
    if len(values) < 2:
        return None
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _parse_prices(value, line_number: int) -> list:
    text = _required_text({'prices': value}, 'prices', line_number)
    prices = []
    for item in text.split('|'):
        item = item.strip()
        if not item:
            continue
        try:
            price = float(item)
        except ValueError as exc:
            raise ValueError(
                f'rotation CSV 第 {line_number} 行 prices 不是有效数字: {item}'
            ) from exc
        if price <= 0 or not math.isfinite(price):
            raise ValueError(f'rotation CSV 第 {line_number} 行 prices 必须大于 0')
        prices.append(price)
    if not prices:
        raise ValueError(f'rotation CSV 第 {line_number} 行 prices 不能为空')
    return prices


def _is_blank_row(row: dict) -> bool:
    return all(value in (None, '') for value in row.values())


def _required_text(row: dict, field: str, line_number: int) -> str:
    value = row.get(field)
    if value in (None, ''):
        raise ValueError(f'rotation CSV 第 {line_number} 行字段 {field} 不能为空')
    return str(value)


def _required_float(row: dict, field: str, line_number: int) -> float:
    return _float(row, field, line_number)


def _non_negative_float(row: dict, field: str, line_number: int) -> float:
    value = _float(row, field, line_number)
    if value < 0:
        raise ValueError(f'rotation CSV 第 {line_number} 行字段 {field} 不能小于 0')
    return value


def _float(row: dict, field: str, line_number: int) -> float:
    value = row.get(field)
    if value in (None, ''):
        raise ValueError(f'rotation CSV 第 {line_number} 行字段 {field} 不能为空')
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(
            f'rotation CSV 第 {line_number} 行字段 {field} 不是有效数字: {value}'
        ) from exc
    if not math.isfinite(number):
        raise ValueError(f'rotation CSV 第 {line_number} 行字段 {field} 不是有限数字')
    return number
