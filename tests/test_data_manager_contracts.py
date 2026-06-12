from datetime import datetime, timedelta, timezone
import time

import numpy as np
import pytest

from data.contracts import DataFetchError
from data.data_manager import DataManager


class BrokenMXDataAdapter:

    def __init__(self, realtime=None, history=None, nav=None):
        self.realtime = realtime
        self.history = history
        self.nav = nav

    def connect(self):
        pass

    def disconnect(self):
        pass

    def health_check(self):
        return {
            'service': 'BrokenMXDataAdapter',
            'mode': 'mock',
            'connected': True,
            'available': True,
            'mock': True,
            'error': '',
        }

    def get_etf_realtime(self, symbol):
        return self.realtime

    def get_etf_history(self, symbol, start_date, end_date):
        return self.history

    def get_etf_nav(self, symbol):
        return self.nav


class ExplodingMXDataAdapter(BrokenMXDataAdapter):

    def get_etf_realtime(self, symbol):
        raise RuntimeError('upstream timeout')


class CountingHistoryAdapter(BrokenMXDataAdapter):

    def __init__(self, histories):
        super().__init__()
        self.histories = list(histories)
        self.calls = 0

    def get_etf_history(self, symbol, start_date, end_date):
        history = self.histories[min(self.calls, len(self.histories) - 1)]
        self.calls += 1
        return history


def _manager_with_adapter(adapter, config_overrides=None):
    config = {
        'mx_data': {'mode': 'mock'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    }
    config.update(config_overrides or {})
    manager = DataManager(config)
    manager.mx_data = adapter
    return manager


def test_get_etf_realtime_returns_complete_mock_quote_contract():
    manager = DataManager({
        'mx_data': {'mode': 'mock'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    })
    manager.connect()

    quote = manager.get_etf_realtime('510300')

    assert set(quote) == set(DataManager.QUOTE_FIELDS)
    assert quote['symbol'] == '510300'
    assert quote['pre_close'] == 0.0


def test_get_etf_nav_returns_complete_mock_nav_contract():
    manager = DataManager({
        'mx_data': {'mode': 'mock'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    })
    manager.connect()

    nav = manager.get_etf_nav('510300')

    assert set(nav) == set(DataManager.NAV_FIELDS)
    assert nav['symbol'] == '510300'
    assert nav['timestamp'] == ''


def test_default_config_allows_empty_mock_timestamp():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': 0.0,
            'open': 0.0,
            'high': 0.0,
            'low': 0.0,
            'pre_close': 0.0,
            'volume': 0,
            'amount': 0.0,
            'timestamp': '',
        }
    ))

    quote = manager.get_etf_realtime('510300')

    assert quote['timestamp'] == ''


def test_get_etf_realtime_rejects_missing_required_fields():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': 4.0,
        }
    ))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'MISSING_FIELDS'
    assert exc.value.source == 'mx_data.realtime'


def test_get_etf_realtime_rejects_none_record():
    manager = _manager_with_adapter(BrokenMXDataAdapter(realtime=None))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'NULL_DATA'
    assert exc.value.source == 'mx_data.realtime'


def test_get_etf_realtime_rejects_empty_record():
    manager = _manager_with_adapter(BrokenMXDataAdapter(realtime={}))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'EMPTY_DATA'
    assert exc.value.source == 'mx_data.realtime'


def test_get_etf_realtime_rejects_invalid_numeric_field():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': 'bad',
            'open': 4.0,
            'high': 4.1,
            'low': 3.9,
            'pre_close': 3.95,
            'volume': 100,
            'amount': 40000.0,
            'timestamp': '2026-06-02 10:00:00',
        }
    ))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'INVALID_FIELD_VALUE'
    assert exc.value.source == 'mx_data.realtime'
    assert '字段 price 必须是有限数字' in str(exc.value)


def test_get_etf_realtime_rejects_negative_volume():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': 4.0,
            'open': 4.0,
            'high': 4.1,
            'low': 3.9,
            'pre_close': 3.95,
            'volume': -1,
            'amount': 40000.0,
            'timestamp': '2026-06-02 10:00:00',
        }
    ))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'INVALID_FIELD_VALUE'
    assert exc.value.source == 'mx_data.realtime'
    assert '字段 volume 必须是非负整数' in str(exc.value)


def test_get_etf_realtime_accepts_numpy_numeric_scalars():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': np.float32(4.0),
            'open': np.float64(4.0),
            'high': np.float64(4.1),
            'low': np.float64(3.9),
            'pre_close': np.float64(3.95),
            'volume': np.int64(100),
            'amount': np.float64(40000.0),
            'timestamp': '2026-06-02 10:00:00',
        }
    ))

    quote = manager.get_etf_realtime('510300')

    assert quote['price'] == 4.0
    assert quote['volume'] == 100
    assert isinstance(quote['price'], float)
    assert isinstance(quote['volume'], int)


def test_get_etf_nav_allows_negative_premium():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        nav={
            'symbol': '510300',
            'nav': 4.1,
            'price': 4.0,
            'premium': -0.024,
            'timestamp': '2026-06-02 10:00:00',
        }
    ))

    nav = manager.get_etf_nav('510300')

    assert nav['premium'] == -0.024


def test_get_etf_realtime_rejects_stale_timestamp_when_configured():
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            realtime={
                'symbol': '510300',
                'price': 4.0,
                'open': 4.0,
                'high': 4.1,
                'low': 3.9,
                'pre_close': 3.95,
                'volume': 100,
                'amount': 40000.0,
                'timestamp': '2000-01-01T10:00:00',
            }
        ),
        {'max_realtime_age_seconds': 60},
    )

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'STALE_DATA'
    assert exc.value.source == 'mx_data.realtime'


def test_get_etf_realtime_revalidates_cached_timestamp_when_configured():
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            realtime={
                'symbol': '510300',
                'price': 4.0,
                'open': 4.0,
                'high': 4.1,
                'low': 3.9,
                'pre_close': 3.95,
                'volume': 100,
                'amount': 40000.0,
                'timestamp': timestamp,
            }
        ),
        {'max_realtime_age_seconds': 60},
    )
    manager.get_etf_realtime('510300')
    manager.cache._cache['realtime_510300']['value']['timestamp'] = (
        '2000-01-01T10:00:00'
    )

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'STALE_DATA'
    assert exc.value.source == 'mx_data.realtime'


def test_get_etf_realtime_limits_cache_ttl_to_remaining_freshness():
    timestamp = (datetime.now(timezone.utc) - timedelta(seconds=55)).isoformat(
        timespec='seconds'
    )
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            realtime={
                'symbol': '510300',
                'price': 4.0,
                'open': 4.0,
                'high': 4.1,
                'low': 3.9,
                'pre_close': 3.95,
                'volume': 100,
                'amount': 40000.0,
                'timestamp': timestamp,
            }
        ),
        {'max_realtime_age_seconds': 60},
    )

    manager.get_etf_realtime('510300')

    remaining_cache_ttl = (
        manager.cache._cache['realtime_510300']['expire_at'] - time.time()
    )
    assert 0 < remaining_cache_ttl <= 6


def test_get_etf_realtime_accepts_fresh_timestamp_when_configured():
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            realtime={
                'symbol': '510300',
                'price': 4.0,
                'open': 4.0,
                'high': 4.1,
                'low': 3.9,
                'pre_close': 3.95,
                'volume': 100,
                'amount': 40000.0,
                'timestamp': timestamp,
            }
        ),
        {'max_realtime_age_seconds': 60},
    )

    quote = manager.get_etf_realtime('510300')

    assert quote['timestamp'] == timestamp


def test_get_etf_realtime_rejects_far_future_timestamp_when_configured():
    timestamp = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(
        timespec='seconds'
    )
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            realtime={
                'symbol': '510300',
                'price': 4.0,
                'open': 4.0,
                'high': 4.1,
                'low': 3.9,
                'pre_close': 3.95,
                'volume': 100,
                'amount': 40000.0,
                'timestamp': timestamp,
            }
        ),
        {
            'max_realtime_age_seconds': 60,
            'max_timestamp_future_skew_seconds': 60,
        },
    )

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'FUTURE_DATA'
    assert exc.value.source == 'mx_data.realtime'


def test_parse_timestamp_applies_configured_timezone_to_naive_timestamp():
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(),
        {'timestamp_timezone_offset': '+08:00'},
    )

    parsed = manager._parse_timestamp('2026-06-04T17:00:00', 'test.source')

    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(hours=8)


def test_parse_timestamp_preserves_explicit_timezone():
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(),
        {'timestamp_timezone_offset': '+08:00'},
    )

    parsed = manager._parse_timestamp(
        '2026-06-04T17:00:00+00:00',
        'test.source',
    )

    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_get_etf_nav_rejects_missing_timestamp_when_freshness_configured():
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            nav={
                'symbol': '510300',
                'nav': 4.1,
                'price': 4.0,
                'premium': -0.024,
                'timestamp': '',
            }
        ),
        {'max_nav_age_seconds': 60},
    )

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_nav('510300')

    assert exc.value.error_code == 'MISSING_TIMESTAMP'
    assert exc.value.source == 'mx_data.nav'


def test_get_etf_nav_rejects_invalid_timestamp_when_freshness_configured():
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            nav={
                'symbol': '510300',
                'nav': 4.1,
                'price': 4.0,
                'premium': -0.024,
                'timestamp': 'not-a-time',
            }
        ),
        {'max_nav_age_seconds': 60},
    )

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_nav('510300')

    assert exc.value.error_code == 'INVALID_TIMESTAMP'
    assert exc.value.source == 'mx_data.nav'


def test_get_etf_nav_accepts_timezone_aware_timestamp_when_configured():
    timestamp = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
        timespec='seconds'
    )
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(
            nav={
                'symbol': '510300',
                'nav': 4.1,
                'price': 4.0,
                'premium': -0.024,
                'timestamp': timestamp,
            }
        ),
        {'max_nav_age_seconds': 60},
    )

    nav = manager.get_etf_nav('510300')

    assert nav['timestamp'] == timestamp


def test_normalize_field_rejects_unclassified_contract_field():
    manager = _manager_with_adapter(BrokenMXDataAdapter())

    with pytest.raises(RuntimeError, match='字段 unclassified 缺少校验规则'):
        manager._normalize_field('unclassified', 'value', 'test.source')


def test_get_etf_history_rejects_non_list_shape():
    manager = _manager_with_adapter(BrokenMXDataAdapter(history={'date': '2026-06-02'}))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_history('510300', '2026-06-01', '2026-06-02')

    assert exc.value.error_code == 'INVALID_DATA_SHAPE'
    assert exc.value.source == 'mx_data.history'


def test_get_etf_history_rejects_records_with_missing_fields():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        history=[{
            'date': '2026-06-02',
            'close': 4.0,
        }]
    ))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_history('510300', '2026-06-01', '2026-06-02')

    assert exc.value.error_code == 'MISSING_FIELDS'
    assert exc.value.source == 'mx_data.history'


def test_get_etf_history_rejects_non_finite_close():
    manager = _manager_with_adapter(BrokenMXDataAdapter(
        history=[{
            'date': '2026-06-02',
            'open': 4.0,
            'high': 4.1,
            'low': 3.9,
            'close': float('nan'),
            'volume': 100,
            'amount': 40000.0,
        }]
    ))

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_history('510300', '2026-06-01', '2026-06-02')

    assert exc.value.error_code == 'INVALID_FIELD_VALUE'
    assert exc.value.source == 'mx_data.history'
    assert '字段 close 必须是有限数字' in str(exc.value)


def test_normalized_quote_is_cached_after_first_fetch():
    adapter = BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': 4.0,
            'open': 4.0,
            'high': 4.1,
            'low': 3.9,
            'pre_close': 3.95,
            'volume': 100,
            'amount': 40000.0,
            'timestamp': '2026-06-02 10:00:00',
            'adapter_extra': 'not part of contract',
        }
    )
    manager = _manager_with_adapter(adapter)

    quote = manager.get_etf_realtime('510300')
    adapter.realtime = {'symbol': '510300'}
    cached = manager.get_etf_realtime('510300')

    assert quote == cached
    assert set(cached) == set(DataManager.QUOTE_FIELDS)
    assert 'adapter_extra' not in cached
    assert cached['price'] == 4.0
    assert isinstance(cached['price'], float)


def test_expired_quote_cache_refetches_from_adapter():
    adapter = BrokenMXDataAdapter(
        realtime={
            'symbol': '510300',
            'price': 4.0,
            'open': 4.0,
            'high': 4.1,
            'low': 3.9,
            'pre_close': 3.95,
            'volume': 100,
            'amount': 40000.0,
            'timestamp': '2026-06-02 10:00:00',
        }
    )
    manager = _manager_with_adapter(adapter)

    first_quote = manager.get_etf_realtime('510300')
    manager.cache._cache['realtime_510300']['expire_at'] = 0
    adapter.realtime = {
        'symbol': '510300',
        'price': 4.2,
        'open': 4.0,
        'high': 4.3,
        'low': 3.9,
        'pre_close': 3.95,
        'volume': 120,
        'amount': 50400.0,
        'timestamp': '2026-06-02 10:01:00',
    }

    refetched_quote = manager.get_etf_realtime('510300')

    assert first_quote['price'] == 4.0
    assert refetched_quote['price'] == 4.2
    assert refetched_quote['timestamp'] == '2026-06-02 10:01:00'


def test_get_etf_history_uses_configured_cache_ttl():
    history = [{
        'date': '2026-06-02',
        'open': 4.0,
        'high': 4.1,
        'low': 3.9,
        'close': 4.05,
        'volume': 100,
        'amount': 40500.0,
    }]
    manager = _manager_with_adapter(
        CountingHistoryAdapter([history]),
        {'history_cache_ttl_seconds': 30},
    )

    manager.get_etf_history('510300', '2026-06-01', '2026-06-02')

    remaining_cache_ttl = (
        manager.cache._cache['history_510300_2026-06-01_2026-06-02']['expire_at']
        - time.time()
    )
    assert 0 < remaining_cache_ttl <= 31


def test_cache_policy_reports_history_cache_ttl():
    manager = _manager_with_adapter(
        BrokenMXDataAdapter(),
        {'history_cache_ttl_seconds': 30},
    )

    assert manager.cache_policy() == {'history_ttl_seconds': 30}


def test_get_etf_history_can_disable_cache_with_zero_ttl():
    first_history = [{
        'date': '2026-06-02',
        'open': 4.0,
        'high': 4.1,
        'low': 3.9,
        'close': 4.05,
        'volume': 100,
        'amount': 40500.0,
    }]
    second_history = [{
        'date': '2026-06-02',
        'open': 4.2,
        'high': 4.3,
        'low': 4.1,
        'close': 4.25,
        'volume': 120,
        'amount': 51000.0,
    }]
    adapter = CountingHistoryAdapter([first_history, second_history])
    manager = _manager_with_adapter(
        adapter,
        {'history_cache_ttl_seconds': 0},
    )

    first = manager.get_etf_history('510300', '2026-06-01', '2026-06-02')
    second = manager.get_etf_history('510300', '2026-06-01', '2026-06-02')

    assert adapter.calls == 2
    assert first[0]['close'] == 4.05
    assert second[0]['close'] == 4.25


def test_data_manager_wraps_unexpected_adapter_errors():
    manager = _manager_with_adapter(ExplodingMXDataAdapter())

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'ADAPTER_ERROR'
    assert exc.value.source == 'mx_data.realtime'
    assert isinstance(exc.value.__cause__, RuntimeError)
