import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from config.settings import SYSTEM_CONFIG


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_provider_config(tmp_path, provider_source: str) -> Path:
    provider = tmp_path / 'history_provider.py'
    provider.write_text(provider_source, encoding='utf-8')
    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data'] = {
        'mode': 'real',
        'timeout': 10,
        'history_command': [
            sys.executable,
            str(provider),
            '{symbol}',
            '{start_date}',
            '{end_date}',
        ],
    }
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    return config_path


def test_cli_history_probe_validates_real_provider_contract(tmp_path):
    config_path = _write_provider_config(
        tmp_path,
        """
import json
import sys

assert sys.argv[1:] == ['510300', '2026-01-01', '2026-01-02']
print(json.dumps([
    {
        'date': '2026-01-01',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    },
    {
        'date': '2026-01-02',
        'open': 4.1,
        'high': 4.3,
        'low': 4.0,
        'close': 4.2,
        'volume': 1100,
        'amount': 4620.0,
    },
]))
""".strip(),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'history',
            'probe',
            '--config',
            str(config_path),
            '--symbol',
            '510300',
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--json',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    result = json.loads(completed.stdout)

    assert result == {
        'available': True,
        'symbol': '510300',
        'start_date': '2026-01-01',
        'end_date': '2026-01-02',
        'row_count': 2,
        'first_date': '2026-01-01',
        'last_date': '2026-01-02',
        'cache': {
            'history_ttl_seconds': 3600,
            'history_cache_hits': 0,
            'history_cache_misses': 1,
            'last_history_cache_key': 'history_510300_2026-01-01_2026-01-02',
            'last_history_cache_hit': False,
        },
        'provider_status': {
            'service': 'MXDataAdapter',
            'mode': 'real',
            'connected': True,
            'available': False,
            'mock': False,
            'error': '',
            'history_provider': 'command',
            'history_provider_count': 1,
            'history_provider_ready_count': 1,
            'history_providers': [
                {'name': 'default', 'ready': True, 'missing_env': []},
            ],
            'history_available': True,
            'last_history_provider': 'default',
            'last_history_attempts': 1,
            'last_history_error': '',
            'last_history_failures': [],
        },
    }


def test_cli_history_probe_json_reports_successful_fallback(tmp_path):
    primary_provider = tmp_path / 'primary_history_provider.py'
    primary_provider.write_text(
        """
import sys

print('primary unavailable', file=sys.stderr)
raise SystemExit(1)
""".strip(),
        encoding='utf-8',
    )
    backup_provider = tmp_path / 'backup_history_provider.py'
    backup_provider.write_text(
        """
import json

print(json.dumps([
    {
        'date': '2026-01-01',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    },
    {
        'date': '2026-01-02',
        'open': 4.1,
        'high': 4.3,
        'low': 4.0,
        'close': 4.2,
        'volume': 1100,
        'amount': 4620.0,
    },
]))
""".strip(),
        encoding='utf-8',
    )
    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data'] = {
        'mode': 'real',
        'timeout': 10,
        'history_providers': [
            {
                'name': 'primary',
                'command': [
                    sys.executable,
                    str(primary_provider),
                    '{symbol}',
                    '{start_date}',
                    '{end_date}',
                ],
            },
            {
                'name': 'backup',
                'command': [
                    sys.executable,
                    str(backup_provider),
                    '{symbol}',
                    '{start_date}',
                    '{end_date}',
                ],
            },
        ],
    }
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'history',
            'probe',
            '--config',
            str(config_path),
            '--symbol',
            '510300',
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--json',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    result = json.loads(completed.stdout)

    assert result['available'] is True
    assert result['provider_status']['last_history_provider'] == 'backup'
    assert result['provider_status']['last_history_attempts'] == 2
    assert result['provider_status']['last_history_failures'] == [
        {
            'provider': 'primary',
            'attempt': 1,
            'error_code': 'REAL_HISTORY_PROVIDER_FAILED',
            'error': (
                'history provider primary exited with 1: primary unavailable'
            ),
        },
    ]


def test_cli_history_probe_text_reports_successful_fallback(tmp_path):
    primary_provider = tmp_path / 'primary_history_provider.py'
    primary_provider.write_text(
        """
import sys

print('primary unavailable', file=sys.stderr)
raise SystemExit(1)
""".strip(),
        encoding='utf-8',
    )
    backup_provider = tmp_path / 'backup_history_provider.py'
    backup_provider.write_text(
        """
import json

print(json.dumps([
    {
        'date': '2026-01-01',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    },
]))
""".strip(),
        encoding='utf-8',
    )
    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data'] = {
        'mode': 'real',
        'timeout': 10,
        'history_providers': [
            {
                'name': 'primary',
                'command': [
                    sys.executable,
                    str(primary_provider),
                    '{symbol}',
                    '{start_date}',
                    '{end_date}',
                ],
            },
            {
                'name': 'backup',
                'command': [
                    sys.executable,
                    str(backup_provider),
                    '{symbol}',
                    '{start_date}',
                    '{end_date}',
                ],
            },
        ],
    }
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'history',
            'probe',
            '--config',
            str(config_path),
            '--symbol',
            '510300',
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert '历史 provider: last=backup, attempts=2, failures=1' in completed.stdout
    assert (
        '历史 provider failures: primary#1 REAL_HISTORY_PROVIDER_FAILED'
    ) in completed.stdout


def test_cli_history_probe_rejects_rows_outside_requested_range(tmp_path):
    config_path = _write_provider_config(
        tmp_path,
        """
import json

print(json.dumps([
    {
        'date': '2025-12-31',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    },
]))
""".strip(),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'history',
            'probe',
            '--config',
            str(config_path),
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 2
    assert '历史 provider 返回了请求区间外的数据' in completed.stderr
    assert 'Traceback' not in completed.stderr


def test_cli_history_probe_json_reports_provider_failure(tmp_path):
    config_path = _write_provider_config(
        tmp_path,
        """
print('not json')
""".strip(),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'history',
            'probe',
            '--config',
            str(config_path),
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--json',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    result = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert completed.stderr == ''
    assert result['available'] is False
    assert result['symbol'] == '510300'
    assert result['start_date'] == '2026-01-01'
    assert result['end_date'] == '2026-01-02'
    assert result['error_code'] == 'INVALID_PROVIDER_RESPONSE'
    assert result['source'] == 'MXDataAdapter'
    assert result['error'] == (
        'MXDataAdapter history provider output is not valid JSON'
    )
    assert result['cache'] == {
        'history_ttl_seconds': 3600,
        'history_cache_hits': 0,
        'history_cache_misses': 1,
        'last_history_cache_key': 'history_510300_2026-01-01_2026-01-02',
        'last_history_cache_hit': False,
    }
    assert result['provider_status'] == {
        'service': 'MXDataAdapter',
        'mode': 'real',
        'connected': True,
        'available': False,
        'mock': False,
        'error': '',
        'history_provider': 'command',
        'history_provider_count': 1,
        'history_provider_ready_count': 1,
        'history_providers': [
            {'name': 'default', 'ready': True, 'missing_env': []},
        ],
        'history_available': True,
        'last_history_provider': None,
        'last_history_attempts': 1,
        'last_history_error': (
            'default attempt 1: '
            'MXDataAdapter history provider output is not valid JSON'
        ),
        'last_history_failures': [
            {
                'provider': 'default',
                'attempt': 1,
                'error_code': 'INVALID_PROVIDER_RESPONSE',
                'error': (
                    'MXDataAdapter history provider output is not valid JSON'
                ),
            },
        ],
    }


def test_cli_history_probe_json_reports_contract_failure_diagnostics(tmp_path):
    config_path = _write_provider_config(
        tmp_path,
        """
import json

print(json.dumps([
    {
        'date': '2025-12-31',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    },
]))
""".strip(),
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'history',
            'probe',
            '--config',
            str(config_path),
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--json',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    result = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert completed.stderr == ''
    assert {
        'available': False,
        'error_code': 'HISTORY_PROBE_CONTRACT_FAILED',
        'source': 'history_probe',
        'error': '历史 provider 返回了请求区间外的数据',
    }.items() <= result.items()
    assert result['cache']['history_cache_misses'] == 1
    assert result['provider_status']['last_history_provider'] == 'default'
    assert result['provider_status']['last_history_failures'] == []
