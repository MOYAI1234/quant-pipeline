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
    }


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
    assert result == {
        'available': False,
        'symbol': '510300',
        'start_date': '2026-01-01',
        'end_date': '2026-01-02',
        'error_code': 'INVALID_PROVIDER_RESPONSE',
        'source': 'MXDataAdapter',
        'error': 'MXDataAdapter history provider output is not valid JSON',
    }
