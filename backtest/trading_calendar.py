import re
from datetime import date, datetime
from typing import Iterable


DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}')


class TradingCalendar:
    """基础交易日历；显式交易日优先于同日的休市配置。"""

    def __init__(
        self,
        holidays: Iterable[str | date] = (),
        extra_trading_days: Iterable[str | date] = (),
    ):
        self.holidays = frozenset(
            _to_date(value, allow_timestamp=False) for value in holidays
        )
        self.extra_trading_days = frozenset(
            _to_date(value, allow_timestamp=False)
            for value in extra_trading_days
        )

    def is_trading_day(self, value: str | date | datetime) -> bool:
        trading_date = _to_date(value, allow_timestamp=True)
        if trading_date in self.extra_trading_days:
            return True
        return trading_date.weekday() < 5 and trading_date not in self.holidays


def _to_date(
    value: str | date | datetime,
    *,
    allow_timestamp: bool,
) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError('交易日历日期必须是 YYYY-MM-DD')
    try:
        if allow_timestamp and ('T' in value or ' ' in value):
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
        if DATE_PATTERN.fullmatch(value) is None:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'交易日历日期必须是 YYYY-MM-DD: {value}') from exc
