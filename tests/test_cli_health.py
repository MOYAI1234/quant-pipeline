import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli import commands as cli_commands


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cli_health_outputs_adapter_statuses():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'health',
            '--no-state',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert '数据源状态: OK (mock)' in completed.stdout
    assert '- 缓存: history_ttl_seconds=3600' in completed.stdout
    assert 'history_hits=0' in completed.stdout
    assert 'history_misses=0' in completed.stdout
    assert 'last_history_hit=-' in completed.stdout
    assert '- mx_data: 可用, mode=mock' in completed.stdout
    assert (
        '- mx_data history: 不可用, provider=-, ready=0/0, '
        'last=-, attempts=0, failures=0'
    ) in completed.stdout
    assert '- mx_xuangu: 可用, mode=mock' in completed.stdout
    assert '- mx_search: 可用, mode=mock' in completed.stdout


def test_cli_health_json_outputs_structured_summary():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'health',
            '--json',
            '--no-state',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    summary = json.loads(completed.stdout)

    assert summary['available'] is True
    assert summary['mock'] is True
    assert summary['cache']['history_ttl_seconds'] == 3600
    assert summary['cache']['history_cache_hits'] == 0
    assert summary['cache']['history_cache_misses'] == 0
    assert summary['cache']['last_history_cache_hit'] is None
    assert summary['adapters']['mx_data']['service'] == 'MXDataAdapter'


def test_cli_health_summary_treats_empty_adapters_as_unavailable():
    summary = cli_commands._build_health_summary({})

    assert summary == {
        'available': False,
        'mock': False,
        'adapters': {},
        'cache': {},
    }


def test_cli_health_summary_keeps_partial_real_adapter_unavailable():
    summary = cli_commands._build_health_summary({
        'mx_data': {
            'service': 'MXDataAdapter',
            'mode': 'real',
            'connected': True,
            'available': False,
            'history_available': True,
            'mock': False,
            'error': '',
        },
    })

    assert summary['available'] is False
    assert summary['mock'] is False
    assert summary['adapters']['mx_data']['history_available'] is True


def test_cli_health_text_includes_history_provider_summary():
    summary = cli_commands._build_health_summary({
        'mx_data': {
            'service': 'MXDataAdapter',
            'mode': 'real',
            'connected': True,
            'available': False,
            'history_available': True,
            'history_provider': 'command',
            'history_provider_count': 2,
            'history_provider_ready_count': 2,
            'last_history_provider': 'backup',
            'last_history_attempts': 2,
            'last_history_failures': [{
                'provider': 'primary',
                'attempt': 1,
                'error_code': 'REAL_HISTORY_PROVIDER_FAILED',
            }],
            'mock': False,
            'error': '',
        },
    })

    rendered = cli_commands._render_health_summary(summary)

    assert (
        '- mx_data history: 可用, provider=command, ready=2/2, '
        'last=backup, attempts=2, failures=1'
    ) in rendered
    assert (
        '- mx_data history failures: '
        'primary#1 REAL_HISTORY_PROVIDER_FAILED'
    ) in rendered


def test_cli_health_strict_exits_when_adapter_is_unavailable(monkeypatch):
    class FakeDataManager:

        def connect(self):
            pass

        def disconnect(self):
            pass

        def health_check(self):
            return {
                'mx_data': {
                    'service': 'MXDataAdapter',
                    'mode': 'real',
                    'connected': False,
                    'available': False,
                    'mock': False,
                    'error': 'real mode not implemented',
                },
            }

    class FakeSystem:

        def __init__(self):
            self.data_manager = FakeDataManager()

    monkeypatch.setattr(cli_commands, 'QuantPipeline', lambda config: FakeSystem())

    args = SimpleNamespace(json=False, strict=True, no_state=True, state_path=None)
    with pytest.raises(SystemExit) as exc:
        cli_commands.cmd_health(args)

    assert exc.value.code == 1
