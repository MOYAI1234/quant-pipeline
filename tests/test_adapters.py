import pytest

from adapters.mx_data_adapter import MXDataAdapter
from adapters.mx_search_adapter import MX_SearchAdapter
from adapters.mx_xuangu_adapter import MX_XuanguAdapter
from data.contracts import ServiceUnavailableError
from data.data_manager import DataManager


def test_mock_adapter_health_reports_mock_mode_after_connect():
    adapter = MXDataAdapter({'mode': 'mock'})

    adapter.connect()
    status = adapter.health_check()

    assert status['service'] == 'MXDataAdapter'
    assert status['mode'] == 'mock'
    assert status['connected'] is True
    assert status['available'] is True
    assert status['mock'] is True
    assert status['error'] == ''


def test_real_adapter_is_explicitly_unavailable_until_implemented():
    adapter = MXDataAdapter({'mode': 'real'})

    adapter.connect()
    status = adapter.health_check()

    assert status['mode'] == 'real'
    assert status['connected'] is False
    assert status['available'] is False
    assert status['mock'] is False
    assert status['error'] == 'real mode not implemented'
    with pytest.raises(ServiceUnavailableError) as exc:
        adapter.get_etf_realtime('510300')
    assert exc.value.error_code == 'REAL_MODE_NOT_IMPLEMENTED'


def test_adapter_rejects_unknown_mode():
    with pytest.raises(ValueError, match='不支持的适配器模式'):
        MXDataAdapter({'mode': 'paper'})


def test_data_manager_health_check_returns_structured_adapter_statuses():
    manager = DataManager({
        'mx_data': {'mode': 'mock'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    })

    manager.connect()
    status = manager.health_check()

    assert set(status) == {'mx_data', 'mx_xuangu', 'mx_search'}
    assert status['mx_data']['available'] is True
    assert status['mx_xuangu']['mode'] == 'mock'
    assert status['mx_search']['mock'] is True
    assert manager.is_mock_mode() is True


def test_data_manager_surfaces_real_mode_as_unavailable():
    manager = DataManager({
        'mx_data': {'mode': 'real'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    })

    manager.connect()
    status = manager.health_check()

    assert status['mx_data']['available'] is False
    assert status['mx_data']['error'] == 'real mode not implemented'
    with pytest.raises(ServiceUnavailableError):
        manager.get_etf_realtime('510300')


def test_non_data_adapters_share_mock_contract():
    xuangu = MX_XuanguAdapter({'mode': 'mock'})
    search = MX_SearchAdapter({'mode': 'mock'})

    xuangu.connect()
    search.connect()

    assert xuangu.filter_etfs({'min_volume': 1000000}) == []
    assert search.search_news('ETF') == []
    assert xuangu.health_check()['mock'] is True
    assert search.health_check()['available'] is True
