"""AKShare ETF history provider for mx_data.history_command.

This script is intentionally optional: install akshare in your local
environment before using it. It writes provider JSON to stdout and diagnostic
errors to stderr so MXDataAdapter can consume it as a command provider.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from typing import Any


AKSHARE_COLUMNS = {
    'date': '日期',
    'open': '开盘',
    'close': '收盘',
    'high': '最高',
    'low': '最低',
    'volume': '成交量',
    'amount': '成交额',
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Fetch ETF daily history from AKShare as provider JSON.',
    )
    parser.add_argument('--symbol', required=True, help='ETF code, e.g. 510300')
    parser.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='YYYY-MM-DD')
    parser.add_argument(
        '--adjust',
        default='',
        choices=('', 'qfq', 'hfq'),
        help='AKShare adjust flag; empty means unadjusted',
    )
    args = parser.parse_args(argv)

    try:
        rows = fetch_akshare_history(
            args.symbol,
            args.start_date,
            args.end_date,
            args.adjust,
        )
    except Exception as exc:  # pragma: no cover - exercised in real provider runs.
        print(f'AKShare history provider failed: {exc}', file=sys.stderr)
        return 1

    print(json.dumps({'history': rows}, ensure_ascii=False))
    return 0


def fetch_akshare_history(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = '',
) -> list[dict[str, Any]]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            'missing optional dependency: install akshare before using this provider'
        ) from exc

    frame = ak.fund_etf_hist_em(
        symbol=symbol,
        period='daily',
        start_date=_compact_date(start_date),
        end_date=_compact_date(end_date),
        adjust=adjust,
    )
    return normalize_akshare_records(frame.to_dict('records'))


def normalize_akshare_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, record in enumerate(records, start=1):
        rows.append({
            'date': _date_text(record.get(AKSHARE_COLUMNS['date']), index),
            'open': _number(record.get(AKSHARE_COLUMNS['open']), 'open', index),
            'high': _number(record.get(AKSHARE_COLUMNS['high']), 'high', index),
            'low': _number(record.get(AKSHARE_COLUMNS['low']), 'low', index),
            'close': _number(record.get(AKSHARE_COLUMNS['close']), 'close', index),
            'volume': _number(
                record.get(AKSHARE_COLUMNS['volume']),
                'volume',
                index,
                non_negative=True,
            ),
            'amount': _number(
                record.get(AKSHARE_COLUMNS['amount']),
                'amount',
                index,
                non_negative=True,
            ),
        })
    return sorted(rows, key=lambda row: row['date'])


def _compact_date(value: str) -> str:
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%Y%m%d')
    except ValueError as exc:
        raise ValueError(f'invalid date {value!r}; expected YYYY-MM-DD') from exc


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
    raise ValueError(f'row {index} missing date')


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


if __name__ == '__main__':
    raise SystemExit(main())
