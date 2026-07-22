"""TuShare ETF history provider for mx_data.history_providers.

This script is optional. Install tushare locally and expose the token through
TUSHARE_TOKEN before using it. Set TUSHARE_API_URL when a local reverse proxy
should replace the default TuShare API endpoint. Provider JSON is written to
stdout and diagnostic errors are written to stderr.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


TUSHARE_TOKEN_ENV = 'TUSHARE_TOKEN'
TUSHARE_API_URL_ENV = 'TUSHARE_API_URL'
TUSHARE_VOLUME_LOT_SIZE = 100
TUSHARE_AMOUNT_UNIT_YUAN = 1000
TUSHARE_FUND_DAILY_ROW_LIMIT = 5000
TUSHARE_HISTORY_PAGE_DAYS = 3650
TUSHARE_HISTORY_FIELDS = 'trade_date,open,high,low,close,vol,amount'
VALID_ADJUSTMENTS = {'none', 'qfq'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Fetch unadjusted ETF daily history from TuShare.',
    )
    parser.add_argument('--symbol', required=True, help='ETF code, e.g. 510300')
    parser.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='YYYY-MM-DD')
    parser.add_argument(
        '--adjust',
        choices=sorted(VALID_ADJUSTMENTS),
        default='none',
        help='Price adjustment mode; qfq normalizes fund_adj to the latest close.',
    )
    args = parser.parse_args(argv)

    try:
        rows = fetch_tushare_history(
            args.symbol,
            args.start_date,
            args.end_date,
            adjustment=args.adjust,
        )
    except Exception as exc:  # pragma: no cover - exercised in real provider runs.
        print(f'TuShare history provider failed: {exc}', file=sys.stderr)
        return 1

    print(json.dumps({'history': rows}, ensure_ascii=False))
    return 0


def fetch_tushare_history(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    adjustment: str = 'none',
) -> list[dict[str, Any]]:
    token = os.environ.get(TUSHARE_TOKEN_ENV)
    if not token:
        raise RuntimeError(
            f'missing required environment variable: {TUSHARE_TOKEN_ENV}'
        )

    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError(
            'missing optional dependency: install tushare before using this provider'
        ) from exc

    if adjustment not in VALID_ADJUSTMENTS:
        raise ValueError(f'unknown adjustment mode: {adjustment}')

    client = _build_tushare_client(ts, token)
    records = []
    adjustment_records = []
    ts_code = _to_ts_code(symbol)
    for page_start, page_end in _date_windows(start_date, end_date):
        frame = client.fund_daily(
            ts_code=ts_code,
            start_date=_compact_date(page_start.isoformat()),
            end_date=_compact_date(page_end.isoformat()),
            fields=TUSHARE_HISTORY_FIELDS,
        )
        page_records = frame.to_dict('records')
        if len(page_records) >= TUSHARE_FUND_DAILY_ROW_LIMIT:
            raise RuntimeError(
                'TuShare fund_daily page reached the 5000-row limit; '
                'reduce TUSHARE_HISTORY_PAGE_DAYS or request a narrower date range'
            )
        records.extend(page_records)
        if adjustment == 'qfq':
            adjustment_frame = client.fund_adj(
                ts_code=ts_code,
                start_date=_compact_date(page_start.isoformat()),
                end_date=_compact_date(page_end.isoformat()),
            )
            adjustment_records.extend(adjustment_frame.to_dict('records'))
    if adjustment == 'qfq':
        records = apply_qfq_adjustment(records, adjustment_records)
    return normalize_tushare_records(records)


def apply_qfq_adjustment(
    records: list[dict[str, Any]],
    adjustment_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not records:
        return []
    factors = {
        str(record.get('trade_date', '')).strip(): _number(
            record.get('adj_factor'),
            'adj_factor',
            index,
        )
        for index, record in enumerate(adjustment_records, start=1)
    }
    missing = [
        str(record.get('trade_date', '')).strip()
        for record in records
        if str(record.get('trade_date', '')).strip() not in factors
    ]
    if missing:
        raise RuntimeError(
            'TuShare fund_adj missing trade dates: ' + ', '.join(sorted(set(missing))[:5])
        )
    latest_date = max(str(record.get('trade_date', '')).strip() for record in records)
    latest_factor = factors[latest_date]
    if latest_factor <= 0:
        raise RuntimeError('TuShare latest fund_adj factor must be positive')
    adjusted = []
    for record in records:
        trade_date = str(record.get('trade_date', '')).strip()
        ratio = factors[trade_date] / latest_factor
        item = dict(record)
        for field in ('open', 'high', 'low', 'close'):
            item[field] = _number(item.get(field), field, 0) * ratio
        adjusted.append(item)
    return adjusted


def _build_tushare_client(ts_module: Any, token: str) -> Any:
    client = ts_module.pro_api(token)
    api_url = os.environ.get(TUSHARE_API_URL_ENV, '').strip()
    if api_url:
        if not api_url.startswith(('http://', 'https://')):
            raise ValueError(f'{TUSHARE_API_URL_ENV} must start with http:// or https://')
        setattr(client, '_DataApi__http_url', api_url)
    return client


def normalize_tushare_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for index, record in enumerate(records, start=1):
        rows.append({
            'date': _date_text(record.get('trade_date'), index),
            'open': _number(record.get('open'), 'open', index),
            'high': _number(record.get('high'), 'high', index),
            'low': _number(record.get('low'), 'low', index),
            'close': _number(record.get('close'), 'close', index),
            'volume': _lots_to_shares(record.get('vol'), index),
            'amount': (
                _number(
                    record.get('amount'),
                    'amount',
                    index,
                    non_negative=True,
                )
                * TUSHARE_AMOUNT_UNIT_YUAN
            ),
        })
    return sorted(rows, key=lambda row: row['date'])


def _to_ts_code(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError('symbol must not be empty')
    if '.' in normalized:
        code, exchange = normalized.rsplit('.', 1)
        expected_exchange = _etf_exchange(code, symbol)
        if exchange == expected_exchange:
            return normalized
        raise ValueError(f'invalid TuShare ETF symbol: {symbol!r}')
    exchange = _etf_exchange(normalized, symbol)
    return f'{normalized}.{exchange}'


def _etf_exchange(code: str, original_symbol: str) -> str:
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f'invalid TuShare ETF symbol: {original_symbol!r}')
    if code.startswith('5'):
        return 'SH'
    if code.startswith('1'):
        return 'SZ'
    raise ValueError(f'invalid TuShare ETF symbol: {original_symbol!r}')


def _compact_date(value: str) -> str:
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise ValueError(f'invalid date {value!r}; expected YYYY-MM-DD') from exc


def _date_value(value: str) -> date:
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValueError(f'invalid date {value!r}; expected YYYY-MM-DD') from exc


def _date_windows(start_date: str, end_date: str) -> list[tuple[date, date]]:
    start = _date_value(start_date)
    end = _date_value(end_date)
    if end < start:
        raise ValueError('end-date must not be before start-date')

    windows = []
    current = start
    while current <= end:
        page_end = min(
            current + timedelta(days=TUSHARE_HISTORY_PAGE_DAYS - 1),
            end,
        )
        windows.append((current, page_end))
        current = page_end + timedelta(days=1)
    return windows


def _date_text(value: Any, index: int) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if len(text) == 8 and text.isdigit():
            return f'{text[0:4]}-{text[4:6]}-{text[6:8]}'
        return text
    raise ValueError(f'row {index} missing trade_date')


def _number(
    value: Any,
    field: str,
    index: int,
    non_negative: bool = False,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f'row {index} field {field} must be numeric')
    try:
        number = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f'row {index} field {field} must be numeric') from exc
    if not math.isfinite(number):
        raise ValueError(f'row {index} field {field} must be finite')
    if non_negative and number < 0:
        raise ValueError(f'row {index} field {field} must be non-negative')
    return number


def _lots_to_shares(value: Any, index: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f'row {index} field volume must be numeric')
    try:
        lots = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f'row {index} field volume must be numeric') from exc
    if not lots.is_finite():
        raise ValueError(f'row {index} field volume must be finite')
    if lots < 0:
        raise ValueError(f'row {index} field volume must be non-negative')

    shares = lots * TUSHARE_VOLUME_LOT_SIZE
    if shares != shares.to_integral_value():
        raise ValueError(
            f'row {index} field volume does not convert to whole shares'
        )
    return int(shares)


if __name__ == '__main__':
    raise SystemExit(main())
