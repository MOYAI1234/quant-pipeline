import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from strategy.base import BaseStrategy


@dataclass(frozen=True)
class DualMomentumConfig:
    lookback_days: int = 252
    min_history_days: int = 253
    min_amount: float | None = None
    risk_holdings: int = 1
    defensive_holdings: int = 1
    cash_return: float = 0.0

    def __post_init__(self):
        if self.lookback_days <= 0:
            raise ValueError('lookback_days 必须大于 0')
        if self.min_history_days <= 0:
            raise ValueError('min_history_days 必须大于 0')
        if self.risk_holdings <= 0:
            raise ValueError('risk_holdings 必须大于 0')
        if self.defensive_holdings <= 0:
            raise ValueError('defensive_holdings 必须大于 0')
        if self.min_amount is not None and self.min_amount < 0:
            raise ValueError('min_amount 不能小于 0')

    @property
    def required_prices(self) -> int:
        return max(self.lookback_days + 1, self.min_history_days)


class ETFDualMomentumBacktestStrategy(BaseStrategy):
    """ETF-DUAL-MOM-002 的本地回测适配层。"""

    def __init__(
        self,
        risk_assets: list[str],
        defensive_assets: list[str],
        factor_config: DualMomentumConfig | None = None,
        *,
        rebalance_dates: set[str] | None = None,
        execution_buffer_rate: float = 0.0,
        name: str = 'ETF-DUAL-MOM-002 本地回测',
    ):
        risk_assets = _normalize_symbols(risk_assets, 'risk_assets')
        defensive_assets = _normalize_symbols(defensive_assets, 'defensive_assets')
        overlap = set(risk_assets) & set(defensive_assets)
        if overlap:
            raise ValueError(
                'risk_assets 和 defensive_assets 不能重复: '
                + ', '.join(sorted(overlap))
            )
        if (
            isinstance(execution_buffer_rate, bool)
            or not isinstance(execution_buffer_rate, (int, float))
            or not math.isfinite(float(execution_buffer_rate))
            or execution_buffer_rate < 0
            or execution_buffer_rate >= 1
        ):
            raise ValueError('execution_buffer_rate 必须在 0 到 1 之间，且小于 1')

        etf_pool = risk_assets + defensive_assets
        super().__init__({
            'name': name,
            'symbol': etf_pool[0],
            'etf_pool': etf_pool,
        })
        self.risk_assets = risk_assets
        self.defensive_assets = defensive_assets
        self.etf_pool = etf_pool
        self.factor_config = factor_config or DualMomentumConfig()
        self.rebalance_dates = set(rebalance_dates or [])
        self.execution_buffer_rate = float(execution_buffer_rate)
        self.selected_etfs = []
        self.evaluation_count = 0
        self.selected_history = []
        self.regime_counts = Counter()
        self.rejection_reasons = Counter()
        self.last_evaluation = None

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        date = data.get('_date', data.get('date', data.get('timestamp', '')))
        if self.rebalance_dates and date not in self.rebalance_dates:
            return []

        snapshot = _market_data_to_snapshot(data, self.etf_pool)
        evaluation = evaluate_snapshot(
            snapshot,
            self.factor_config,
            self.risk_assets,
            self.defensive_assets,
        )
        self.evaluation_count += 1
        self.last_evaluation = evaluation
        self.selected_etfs = list(evaluation['selected'])
        self.selected_history.append({
            'date': evaluation['date'],
            'regime': evaluation['regime'],
            'selected': list(evaluation['selected']),
        })
        self.regime_counts.update([evaluation['regime']])
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
            shares = int(position['shares'] // 100) * 100
            if price <= 0 or shares <= 0:
                continue
            signals.append({
                'action': 'sell',
                'symbol': symbol,
                'price': price,
                'shares': shares,
                'amount': shares * price,
                'reason': 'ETF-DUAL-MOM-002 月频调仓卖出',
                'timestamp': signal_time,
            })

        if not selected:
            return signals

        target_value = (portfolio or {}).get('total_value', 0) / len(selected)
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
            budget = min(target_value - current_value, available_capital)
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
                'reason': 'ETF-DUAL-MOM-002 月频调仓买入',
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
        amount = amount * (1 - self.execution_buffer_rate)
        commission = max(
            amount * costs['sell_commission_rate'],
            costs['min_commission'],
        )
        return max(amount - commission, 0)

    def _gross_buy_cost(self, amount: float, costs: dict) -> float:
        amount = amount * (1 + self.execution_buffer_rate)
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
        effective_price = price * (1 + self.execution_buffer_rate)
        max_notional = min(
            budget / (1 + costs['buy_commission_rate']),
            budget - costs['min_commission'],
        )
        if max_notional <= 0:
            return 0
        return int(max_notional / effective_price / 100) * 100


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
            bar = {
                'close': _required_float(row, 'close', line_number),
                'prices': _parse_prices(row.get('prices'), line_number),
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


def month_end_dates(history: list) -> set[str]:
    if not history:
        return set()
    selected = {}
    for snapshot in history:
        date = snapshot.get('date', snapshot.get('timestamp', ''))
        if not isinstance(date, str) or len(date) < 7:
            raise ValueError('history 日期必须包含 YYYY-MM')
        selected[date[:7]] = date
    return set(selected.values())


def evaluate_history(
    history: list,
    config: DualMomentumConfig,
    risk_assets: list[str],
    defensive_assets: list[str],
    *,
    rebalance_dates: set[str] | None = None,
    limit: int | None = None,
) -> list:
    dates = rebalance_dates or month_end_dates(history)
    results = []
    for snapshot in history:
        date = snapshot.get('date', snapshot.get('timestamp', ''))
        if date not in dates:
            continue
        results.append(
            evaluate_snapshot(snapshot, config, risk_assets, defensive_assets)
        )
        if limit is not None and len(results) >= limit:
            break
    return results


def evaluate_snapshot(
    snapshot: dict,
    config: DualMomentumConfig,
    risk_assets: list[str],
    defensive_assets: list[str],
) -> dict:
    date = snapshot.get('date', snapshot.get('timestamp', ''))
    symbols = snapshot.get('symbols') or {}
    rejections = []
    factors = {}

    for symbol in _normalize_symbols(risk_assets + defensive_assets, 'assets'):
        if symbol not in symbols:
            rejections.append({'symbol': symbol, 'reason': 'missing_symbol'})
            continue
        factor, reason = calculate_factor(symbol, symbols[symbol], config)
        if factor is None:
            rejections.append({'symbol': symbol, 'reason': reason})
        else:
            factors[symbol] = factor

    risk_ranked = _rank_assets(factors, risk_assets)
    defensive_ranked = _rank_assets(factors, defensive_assets)
    selected = []
    regime = 'cash'

    risk_leaders = [
        item for item in risk_ranked
        if item['momentum'] > config.cash_return
    ]
    if risk_leaders:
        regime = 'risk_on'
        selected = [
            item['symbol']
            for item in risk_leaders[:config.risk_holdings]
        ]
    else:
        defensive_leaders = [
            item for item in defensive_ranked
            if item['momentum'] > config.cash_return
        ]
        if defensive_leaders:
            regime = 'risk_off'
            selected = [
                item['symbol']
                for item in defensive_leaders[:config.defensive_holdings]
            ]

    return {
        'date': date,
        'regime': regime,
        'selected': selected,
        'risk_ranked': risk_ranked,
        'defensive_ranked': defensive_ranked,
        'rejections': rejections,
    }


def calculate_factor(
    symbol: str,
    bar: dict,
    config: DualMomentumConfig,
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
    if config.min_amount is not None and amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return None, 'invalid_amount'
        if amount < config.min_amount:
            return None, 'low_amount amount=%.2f need=%.2f' % (
                amount,
                config.min_amount,
            )

    latest = prices[-1]
    base = prices[-config.lookback_days - 1]
    return {
        'symbol': symbol,
        'momentum': latest / base - 1.0,
        'amount': amount,
    }, None


def backtest_diagnostics(strategy: ETFDualMomentumBacktestStrategy) -> dict:
    selected_count = sum(
        1 for item in strategy.selected_history
        if item['selected']
    )
    return {
        'evaluation_count': strategy.evaluation_count,
        'selected_count': selected_count,
        'empty_count': strategy.evaluation_count - selected_count,
        'regime_counts': dict(strategy.regime_counts),
        'last_selected': (
            strategy.selected_history[-1]['selected']
            if strategy.selected_history else []
        ),
        'rejection_reasons': dict(strategy.rejection_reasons),
    }


def render_text(results: list) -> str:
    lines = []
    for result in results:
        lines.append(f"date={result['date']}")
        lines.append(f"regime={result['regime']}")
        selected = ','.join(result['selected']) if result['selected'] else '[]'
        lines.append(f"selected={selected}")
        _append_ranked(lines, 'risk_ranked', result['risk_ranked'])
        _append_ranked(lines, 'defensive_ranked', result['defensive_ranked'])
        if result['rejections']:
            lines.append('rejections:')
            for rejection in result['rejections']:
                lines.append(
                    f"- {rejection['symbol']}: {rejection['reason']}"
                )
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def render_json(results: list) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2) + '\n'


def _append_ranked(lines: list, label: str, ranked: list) -> None:
    if not ranked:
        return
    lines.append(f'{label}:')
    for item in ranked:
        lines.append(
            "- {symbol} momentum={momentum:.4f}".format(**item)
        )


def _rank_assets(factors: dict, assets: list[str]) -> list:
    return sorted(
        [
            factors[symbol]
            for symbol in assets
            if symbol in factors
        ],
        key=lambda item: item['momentum'],
        reverse=True,
    )


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


def _normalize_symbols(symbols: list[str], label: str) -> list[str]:
    normalized = [symbol.strip() for symbol in symbols if symbol.strip()]
    if not normalized:
        raise ValueError(f'{label} 不能为空')
    seen = set()
    duplicates = []
    for symbol in normalized:
        if symbol in seen:
            duplicates.append(symbol)
        seen.add(symbol)
    if duplicates:
        raise ValueError(f'{label} 包含重复标的: {", ".join(sorted(set(duplicates)))}')
    return normalized


def _base_rejection_reason(reason: str) -> str:
    return reason.split()[0] if reason else 'unknown'


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
