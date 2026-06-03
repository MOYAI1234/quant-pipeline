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
    assert '- mx_data: 可用, mode=mock' in completed.stdout
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
    assert summary['adapters']['mx_data']['service'] == 'MXDataAdapter'


def test_cli_health_summary_treats_empty_adapters_as_unavailable():
    summary = cli_commands._build_health_summary({})

    assert summary == {
        'available': False,
        'mock': False,
        'adapters': {},
    }


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
