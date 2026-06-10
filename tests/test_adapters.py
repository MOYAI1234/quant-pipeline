import sys

import pytest

from adapters.mx_data_adapter import MXDataAdapter
from adapters.mx_search_adapter import MX_SearchAdapter
from adapters.mx_xuangu_adapter import MX_XuanguAdapter
from data.contracts import DataFetchError, ServiceUnavailableError
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


def test_real_adapter_requires_history_provider_configuration():
    adapter = MXDataAdapter({'mode': 'real'})

    adapter.connect()
    status = adapter.health_check()

    assert status['mode'] == 'real'
    assert status['connected'] is False
    assert status['available'] is False
    assert status['mock'] is False
    assert status['error'] == 'real history provider not configured'
    assert status['history_provider'] is None
    assert status['history_available'] is False
    with pytest.raises(ServiceUnavailableError) as exc:
        adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')
    assert exc.value.error_code == 'REAL_HISTORY_PROVIDER_NOT_CONFIGURED'


def test_real_history_provider_command_returns_history_rows(tmp_path):
    provider = tmp_path / 'history_provider.py'
    provider.write_text(
        """
import json
import sys

assert sys.argv[1:] == ['510300', '2026-01-01', '2026-01-02']
print(json.dumps({'history': [
    {
        'date': '2026-01-01',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    }
]}))
""".strip(),
        encoding='utf-8',
    )
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_command': [
            sys.executable,
            str(provider),
            '{symbol}',
            '{start_date}',
            '{end_date}',
        ],
    })

    adapter.connect()
    status = adapter.health_check()
    rows = adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')

    assert status['available'] is False
    assert status['history_provider'] == 'command'
    assert status['history_available'] is True
    assert rows[0]['close'] == 4.1


def test_real_history_provider_rejects_invalid_command_configuration(tmp_path):
    provider = tmp_path / 'history_provider.py'
    provider.write_text('print("[]")', encoding='utf-8')
    invalid_commands = [
        [sys.executable, str(provider), '{unknown}'],
        [sys.executable, str(provider), '{symbol'],
        ['definitely-missing-quant-provider'],
    ]

    for history_command in invalid_commands:
        adapter = MXDataAdapter({
            'mode': 'real',
            'history_command': history_command,
        })

        adapter.connect()
        status = adapter.health_check()

        assert status['connected'] is False
        assert status['available'] is False
        assert status['history_available'] is False
        assert status['error']
        with pytest.raises(ServiceUnavailableError) as exc:
            adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')
        assert exc.value.error_code == 'REAL_HISTORY_PROVIDER_NOT_CONFIGURED'


def test_real_history_provider_rejects_invalid_json(tmp_path):
    provider = tmp_path / 'bad_provider.py'
    provider.write_text("print('not json')", encoding='utf-8')
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_command': [sys.executable, str(provider)],
    })

    adapter.connect()
    with pytest.raises(DataFetchError) as exc:
        adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')

    assert exc.value.error_code == 'INVALID_PROVIDER_RESPONSE'


def test_real_mode_non_history_operations_remain_unavailable(tmp_path):
    provider = tmp_path / 'history_provider.py'
    provider.write_text('import json; print(json.dumps([]))', encoding='utf-8')
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_command': [sys.executable, str(provider)],
    })

    adapter.connect()
    with pytest.raises(ServiceUnavailableError) as exc:
        adapter.get_etf_realtime('510300')

    assert exc.value.error_code == 'REAL_OPERATION_NOT_IMPLEMENTED'


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
    assert status['mx_data']['error'] == 'real history provider not configured'
    assert manager.is_mock_mode() is False
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
