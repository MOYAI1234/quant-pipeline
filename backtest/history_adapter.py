import csv
import math
from pathlib import Path


GRID_HISTORY_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')
ROTATION_HISTORY_FIELDS = ('date', 'symbol', 'close', 'prices', 'volume')


def fetch_grid_history(data_manager, symbol: str, start_date: str, end_date: str) -> list:
    return normalize_grid_history(
        data_manager.get_etf_history(symbol, start_date, end_date)
    )


def fetch_rotation_history(
    data_manager,
    symbols: list,
    start_date: str,
    end_date: str,
    *,
    lookback: int | None = None,
) -> list:
    histories = {
        symbol: data_manager.get_etf_history(symbol, start_date, end_date)
        for symbol in symbols
    }
    return build_rotation_history(histories, lookback=lookback)


def normalize_grid_history(records: list) -> list:
    if not isinstance(records, list):
        raise ValueError('历史行情必须是 list')
    if not records:
        raise ValueError('历史行情没有数据行')
    return [
        _normalize_grid_bar(record, index)
        for index, record in enumerate(records, start=1)
    ]


def build_rotation_history(
    symbol_histories: dict,
    *,
    lookback: int | None = None,
) -> list:
    _validate_lookback(lookback)
    normalized = _normalize_symbol_histories(symbol_histories)
    _reject_duplicate_dates(normalized)
    symbols = list(normalized)
    dates = [row['date'] for row in normalized[symbols[0]]]
    for symbol in symbols[1:]:
        symbol_dates = [row['date'] for row in normalized[symbol]]
        if symbol_dates != dates:
            raise ValueError(f'轮动历史日期序列不一致: {symbol}')

    return _build_rotation_snapshots(normalized, dates, lookback=lookback)


def build_rotation_history_intersection(
    symbol_histories: dict,
    *,
    lookback: int | None = None,
) -> list:
    _validate_lookback(lookback)
    normalized = _normalize_symbol_histories(symbol_histories)
    _reject_duplicate_dates(normalized)
    common_dates = None
    for rows in normalized.values():
        dates = [row['date'] for row in rows]
        symbol_dates = set(dates)
        common_dates = (
            symbol_dates
            if common_dates is None
            else common_dates & symbol_dates
        )
    dates = sorted(common_dates or [])
    if not dates:
        raise ValueError('轮动历史没有共同日期')

    return _build_rotation_snapshots(normalized, dates, lookback=lookback)


def _build_rotation_snapshots(
    normalized: dict,
    dates: list[str],
    *,
    lookback: int | None,
) -> list:
    symbols = list(normalized)
    index_by_symbol = {
        symbol: {row['date']: index for index, row in enumerate(rows)}
        for symbol, rows in normalized.items()
    }
    snapshots = []
    for snapshot_date in dates:
        snapshot_symbols = {}
        for symbol in symbols:
            rows = normalized[symbol]
            index = index_by_symbol[symbol][snapshot_date]
            bar = rows[index]
            start_index = 0 if lookback is None else max(0, index + 1 - lookback)
            snapshot_symbols[symbol] = {
                'close': bar['close'],
                'prices': [row['close'] for row in rows[start_index:index + 1]],
                'volume': bar['volume'],
            }
        snapshots.append({
            'date': snapshot_date,
            'symbols': snapshot_symbols,
        })
    return snapshots


def write_grid_history_csv(path: str, history: list) -> Path:
    rows = normalize_grid_history(history)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=GRID_HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def write_rotation_history_csv(path: str, history: list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=ROTATION_HISTORY_FIELDS)
        writer.writeheader()
        for snapshot in history:
            snapshot_date = snapshot.get('date', snapshot.get('timestamp', ''))
            for symbol, bar in snapshot.get('symbols', {}).items():
                writer.writerow({
                    'date': snapshot_date,
                    'symbol': symbol,
                    'close': bar.get('close', bar.get('price', '')),
                    'prices': '|'.join(str(price) for price in bar.get('prices', [])),
                    'volume': bar.get('volume', ''),
                })
    return output_path


def _normalize_grid_bar(record: dict, index: int) -> dict:
    if not isinstance(record, dict):
        raise ValueError(f'历史行情第 {index} 条必须是 dict')
    return {
        'date': _required_text(record, 'date', index),
        'open': _required_number(record, 'open', index),
        'high': _required_number(record, 'high', index),
        'low': _required_number(record, 'low', index),
        'close': _required_number(record, 'close', index),
        'volume': _required_non_negative_int(record, 'volume', index),
        'amount': _required_number(record, 'amount', index),
    }


def _normalize_symbol(symbol) -> str:
    normalized = str(symbol).strip()
    if not normalized:
        raise ValueError('轮动历史 symbol 不能为空')
    return normalized


def _validate_lookback(lookback: int | None) -> None:
    if lookback is not None and lookback <= 0:
        raise ValueError('lookback 必须大于 0')


def _normalize_symbol_histories(symbol_histories: dict) -> dict:
    if not isinstance(symbol_histories, dict) or not symbol_histories:
        raise ValueError('轮动历史必须是非空 symbol->history 映射')

    normalized = {}
    for symbol, history in symbol_histories.items():
        normalized_symbol = _normalize_symbol(symbol)
        if normalized_symbol in normalized:
            raise ValueError(f'轮动历史 symbol 重复: {normalized_symbol}')
        normalized[normalized_symbol] = sorted(
            normalize_grid_history(history),
            key=lambda row: row['date'],
        )
    return normalized


def _reject_duplicate_dates(normalized: dict) -> None:
    for symbol, rows in normalized.items():
        dates = [row['date'] for row in rows]
        if len(dates) != len(set(dates)):
            raise ValueError(f'轮动历史日期重复: {symbol}')


def _required_text(record: dict, field: str, index: int) -> str:
    value = record.get(field)
    if value in (None, ''):
        raise ValueError(f'历史行情第 {index} 条字段 {field} 不能为空')
    return str(value)


def _required_number(record: dict, field: str, index: int) -> float:
    value = record.get(field)
    if value in (None, ''):
        raise ValueError(f'历史行情第 {index} 条字段 {field} 不能为空')
    if isinstance(value, bool):
        raise ValueError(f'历史行情第 {index} 条字段 {field} 不是有效数字')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'历史行情第 {index} 条字段 {field} 不是有效数字'
        ) from exc
    if not math.isfinite(number):
        raise ValueError(f'历史行情第 {index} 条字段 {field} 不是有限数字')
    if number < 0:
        raise ValueError(f'历史行情第 {index} 条字段 {field} 不能小于 0')
    return number


def _required_non_negative_int(record: dict, field: str, index: int) -> int:
    number = _required_number(record, field, index)
    if not number.is_integer():
        raise ValueError(f'历史行情第 {index} 条字段 {field} 不是有效整数')
    return int(number)
