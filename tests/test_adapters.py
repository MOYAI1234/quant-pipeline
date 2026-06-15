import os
from pathlib import Path
from subprocess import CompletedProcess
import sys

import pytest

from adapters import mx_data_adapter
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


def test_real_history_provider_rejects_non_executable_path_commands(tmp_path, monkeypatch):
    provider_dir = tmp_path / 'provider_dir'
    provider_dir.mkdir()
    provider_file = tmp_path / 'provider.py'
    provider_file.write_text('print("[]")', encoding='utf-8')
    original_access = os.access

    def fake_access(path, mode):
        if Path(path) == provider_file and mode == os.X_OK:
            return False
        return original_access(path, mode)

    monkeypatch.setattr(mx_data_adapter.os, 'access', fake_access)

    for history_command in ([str(provider_dir)], [str(provider_file)]):
        adapter = MXDataAdapter({
            'mode': 'real',
            'history_command': history_command,
        })

        adapter.connect()
        status = adapter.health_check()

        assert status['connected'] is False
        assert status['available'] is False
        assert status['history_available'] is False
        assert status['error'].endswith(f': {history_command[0]}')
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


def test_real_history_providers_fall_back_after_primary_failure(monkeypatch):
    calls = []
    responses = [
        CompletedProcess(['primary'], 1, '', 'primary unavailable'),
        CompletedProcess(
            ['backup'],
            0,
            (
                '{"history": [{"date": "2026-01-01", "open": 4.0, '
                '"high": 4.2, "low": 3.9, "close": 4.1, '
                '"volume": 1000, "amount": 4100.0}]}'
            ),
            '',
        ),
    ]

    def fake_run(command, **_kwargs):
        calls.append(command)
        return responses.pop(0)

    monkeypatch.setattr(
        mx_data_adapter.subprocess,
        'run',
        fake_run,
    )
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {
                'name': 'primary',
                'command': [
                    sys.executable,
                    'primary.py',
                    '{symbol}',
                    '{start_date}',
                    '{end_date}',
                ],
            },
            {
                'name': 'backup',
                'command': [
                    sys.executable,
                    'backup.py',
                    '{symbol}',
                    '{start_date}',
                    '{end_date}',
                ],
            },
        ],
    })

    adapter.connect()
    rows = adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')
    status = adapter.health_check()

    assert rows[0]['close'] == 4.1
    assert calls == [
        [
            sys.executable,
            'primary.py',
            '510300',
            '2026-01-01',
            '2026-01-02',
        ],
        [
            sys.executable,
            'backup.py',
            '510300',
            '2026-01-01',
            '2026-01-02',
        ],
    ]
    assert status['history_provider_count'] == 2
    assert status['last_history_provider'] == 'backup'
    assert status['last_history_attempts'] == 2
    assert 'primary attempt 1' in status['last_history_error']
    assert status['last_history_failures'] == [
        {
            'provider': 'primary',
            'attempt': 1,
            'error_code': 'REAL_HISTORY_PROVIDER_FAILED',
            'error': (
                'history provider primary exited with 1: primary unavailable'
            ),
        },
    ]


def test_real_history_providers_skip_missing_env_and_use_backup(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, '[]', '')

    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    monkeypatch.setattr(mx_data_adapter.subprocess, 'run', fake_run)
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {
                'name': 'tushare',
                'command': [sys.executable, 'tushare_provider.py'],
                'required_env': ['TUSHARE_TOKEN'],
            },
            {
                'name': 'backup',
                'command': [sys.executable, 'backup.py'],
            },
        ],
    })

    adapter.connect()
    assert adapter.get_etf_history(
        '510300',
        '2026-01-01',
        '2026-01-02',
    ) == []

    status = adapter.health_check()
    assert calls == [[sys.executable, 'backup.py']]
    assert status['history_provider_ready_count'] == 1
    assert status['history_providers'] == [
        {
            'name': 'tushare',
            'ready': False,
            'missing_env': ['TUSHARE_TOKEN'],
        },
        {
            'name': 'backup',
            'ready': True,
            'missing_env': [],
        },
    ]
    assert status['last_history_provider'] == 'backup'
    assert status['last_history_attempts'] == 2
    assert status['last_history_failures'][0]['error_code'] == (
        'REAL_HISTORY_PROVIDER_ENV_MISSING'
    )


def test_real_history_provider_is_unavailable_when_required_env_is_missing(
    monkeypatch,
):
    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {
                'name': 'tushare',
                'command': [sys.executable, 'tushare_provider.py'],
                'required_env': ['TUSHARE_TOKEN'],
            },
        ],
    })

    adapter.connect()
    status = adapter.health_check()

    assert status['connected'] is False
    assert status['history_available'] is False
    assert status['history_provider_ready_count'] == 0
    assert 'tushare: TUSHARE_TOKEN' in status['error']
    with pytest.raises(ServiceUnavailableError) as exc:
        adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')
    assert exc.value.error_code == 'REAL_HISTORY_PROVIDER_ENV_MISSING'


def test_real_history_provider_retries_transient_failure(monkeypatch):
    responses = [
        CompletedProcess(['primary'], 1, '', 'temporary failure'),
        CompletedProcess(['primary'], 0, '[]', ''),
    ]
    monkeypatch.setattr(
        mx_data_adapter.subprocess,
        'run',
        lambda *_args, **_kwargs: responses.pop(0),
    )
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_command': [sys.executable, 'primary.py'],
        'history_retry_attempts': 2,
        'history_retry_delay_seconds': 0,
    })

    adapter.connect()
    assert adapter.get_etf_history(
        '510300',
        '2026-01-01',
        '2026-01-02',
    ) == []

    status = adapter.health_check()
    assert status['last_history_provider'] == 'default'
    assert status['last_history_attempts'] == 2


def test_real_history_provider_does_not_retry_invalid_payload_before_fallback(
    monkeypatch,
):
    responses = [
        CompletedProcess(['primary'], 0, 'not json', ''),
        CompletedProcess(['backup'], 0, '[]', ''),
    ]
    monkeypatch.setattr(
        mx_data_adapter.subprocess,
        'run',
        lambda *_args, **_kwargs: responses.pop(0),
    )
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {'name': 'primary', 'command': [sys.executable, 'primary.py']},
            {'name': 'backup', 'command': [sys.executable, 'backup.py']},
        ],
        'history_retry_attempts': 3,
    })

    adapter.connect()
    assert adapter.get_etf_history(
        '510300',
        '2026-01-01',
        '2026-01-02',
    ) == []
    assert adapter.health_check()['last_history_attempts'] == 2


def test_real_history_provider_falls_back_after_non_utf8_output(monkeypatch):
    responses = [
        UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte'),
        CompletedProcess(['backup'], 0, '[]', ''),
    ]

    def fake_run(*_args, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(mx_data_adapter.subprocess, 'run', fake_run)
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {'name': 'primary', 'command': [sys.executable, 'primary.py']},
            {'name': 'backup', 'command': [sys.executable, 'backup.py']},
        ],
        'history_retry_attempts': 3,
    })

    adapter.connect()
    assert adapter.get_etf_history(
        '510300',
        '2026-01-01',
        '2026-01-02',
    ) == []
    status = adapter.health_check()
    assert status['last_history_provider'] == 'backup'
    assert status['last_history_attempts'] == 2
    assert status['last_history_failures'][0]['error_code'] == (
        'INVALID_PROVIDER_RESPONSE'
    )


def test_real_history_providers_fall_back_when_primary_executable_is_missing(
    tmp_path,
):
    backup = tmp_path / 'backup.py'
    backup.write_text('print("[]")', encoding='utf-8')
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {
                'name': 'missing',
                'command': ['definitely-missing-quant-provider'],
            },
            {
                'name': 'backup',
                'command': [sys.executable, str(backup)],
            },
        ],
        'history_retry_attempts': 2,
    })

    adapter.connect()
    assert adapter.health_check()['connected'] is True
    assert adapter.get_etf_history(
        '510300',
        '2026-01-01',
        '2026-01-02',
    ) == []
    status = adapter.health_check()
    assert status['last_history_provider'] == 'backup'
    assert status['last_history_attempts'] == 3
    assert len(status['last_history_failures']) == 2


def test_real_history_providers_report_aggregated_failures(monkeypatch):
    monkeypatch.setattr(
        mx_data_adapter.subprocess,
        'run',
        lambda command, **_kwargs: CompletedProcess(
            command,
            1,
            '',
            f'{command[-1]} unavailable',
        ),
    )
    adapter = MXDataAdapter({
        'mode': 'real',
        'history_providers': [
            {'name': 'primary', 'command': [sys.executable, 'primary.py']},
            {'name': 'backup', 'command': [sys.executable, 'backup.py']},
        ],
        'history_retry_attempts': 2,
    })

    adapter.connect()
    with pytest.raises(ServiceUnavailableError) as exc:
        adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')

    assert exc.value.error_code == 'REAL_HISTORY_PROVIDERS_FAILED'
    assert 'primary attempt 1' in str(exc.value)
    assert 'backup attempt 2' in str(exc.value)
    status = adapter.health_check()
    assert status['last_history_provider'] is None
    assert status['last_history_attempts'] == 4
    assert 'primary attempt 1' in status['last_history_error']


def test_real_history_providers_reject_ambiguous_or_duplicate_configuration():
    invalid_configs = [
        {
            'history_command': [sys.executable, 'legacy.py'],
            'history_providers': [
                {'name': 'primary', 'command': [sys.executable, 'primary.py']},
            ],
        },
        {
            'history_providers': [
                {'name': 'same', 'command': [sys.executable, 'primary.py']},
                {'name': 'same', 'command': [sys.executable, 'backup.py']},
            ],
        },
        {'history_providers': ['not-an-object']},
        {
            'history_providers': [
                {
                    'name': 'primary',
                    'command': [sys.executable, 'primary.py'],
                    'required_env': ['TOKEN', 'TOKEN'],
                },
            ],
        },
        {
            'history_providers': [
                {
                    'name': 'primary',
                    'command': [sys.executable, 'primary.py'],
                    'required_env': None,
                },
            ],
        },
    ]

    for config in invalid_configs:
        adapter = MXDataAdapter({'mode': 'real', **config})
        adapter.connect()

        assert adapter.health_check()['connected'] is False
        with pytest.raises(ServiceUnavailableError) as exc:
            adapter.get_etf_history('510300', '2026-01-01', '2026-01-02')
        assert exc.value.error_code == 'REAL_HISTORY_PROVIDER_NOT_CONFIGURED'


def test_real_history_provider_rejects_invalid_retry_configuration():
    invalid_configs = [
        {'history_retry_attempts': 0},
        {'history_retry_attempts': True},
        {'history_retry_attempts': 11},
        {'history_retry_delay_seconds': -1},
        {'history_retry_delay_seconds': 61},
        {'history_retry_delay_seconds': float('nan')},
    ]

    for extra_config in invalid_configs:
        adapter = MXDataAdapter({
            'mode': 'real',
            'history_command': [sys.executable, 'provider.py'],
            **extra_config,
        })
        adapter.connect()

        assert adapter.health_check()['connected'] is False


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
