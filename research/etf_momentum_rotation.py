import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


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
