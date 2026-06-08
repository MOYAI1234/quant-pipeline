from datetime import date, datetime

import pytest

from backtest.trading_calendar import TradingCalendar


def test_trading_calendar_accepts_weekdays_and_intraday_timestamps():
    calendar = TradingCalendar()

    assert calendar.is_trading_day('2026-01-02')
    assert calendar.is_trading_day(datetime(2026, 1, 2, 9, 30))
    assert calendar.is_trading_day(date(2026, 1, 2))
    assert not calendar.is_trading_day('2026-01-03')


def test_trading_calendar_applies_holidays_and_extra_trading_days():
    calendar = TradingCalendar(
        holidays=['2026-01-02'],
        extra_trading_days=['2026-01-03'],
    )

    assert not calendar.is_trading_day('2026-01-02')
    assert calendar.is_trading_day('2026-01-03T09:30:00')


def test_extra_trading_day_overrides_holiday():
    calendar = TradingCalendar(
        holidays=['2026-01-02'],
        extra_trading_days=['2026-01-02'],
    )

    assert calendar.is_trading_day('2026-01-02')


@pytest.mark.parametrize(
    'value',
    ['2026-02-30', '2026-01-02-extra', '20260102', '2026-W01-5'],
)
def test_trading_calendar_rejects_invalid_configured_date(value):
    with pytest.raises(
        ValueError,
        match='交易日历日期必须是 YYYY-MM-DD',
    ):
        TradingCalendar(holidays=[value])
