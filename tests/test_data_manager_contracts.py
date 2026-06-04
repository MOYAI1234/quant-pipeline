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


def _manager_with_adapter(adapter):
    manager = DataManager({
        'mx_data': {'mode': 'mock'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    })
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


def test_data_manager_wraps_unexpected_adapter_errors():
    manager = _manager_with_adapter(ExplodingMXDataAdapter())

    with pytest.raises(DataFetchError) as exc:
        manager.get_etf_realtime('510300')

    assert exc.value.error_code == 'ADAPTER_ERROR'
    assert exc.value.source == 'mx_data.realtime'
    assert isinstance(exc.value.__cause__, RuntimeError)
