import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli import commands as cli_commands


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_alerts(path: Path):
    events = [
        {
            'message': '亏损告警: -7.00%',
            'level': 'warning',
            'category': 'risk.pnl',
            'payload': {'pnl_percent': -7},
            'timestamp': '2026-06-03T10:00:00',
        },
        {
            'message': '持仓告警: 5格',
            'level': 'warning',
            'category': 'risk.position',
            'payload': {'position': 5},
            'timestamp': '2026-06-03T10:30:00',
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding='utf-8',
    )
    return events


def test_cli_alerts_outputs_recent_events(tmp_path):
    alert_file = tmp_path / 'alerts.jsonl'
    _write_alerts(alert_file)

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'alerts',
            '--alert-file',
            str(alert_file),
            '--limit',
            '1',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert '告警事件: 1 条' in completed.stdout
    assert '- [warning] risk.position: 持仓告警: 5格' in completed.stdout
    assert 'risk.pnl' not in completed.stdout


def test_cli_alerts_json_outputs_structured_events(tmp_path):
    alert_file = tmp_path / 'alerts.jsonl'
    events = _write_alerts(alert_file)

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'alerts',
            '--alert-file',
            str(alert_file),
            '--json',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert json.loads(completed.stdout) == events


def test_cli_alerts_missing_file_outputs_empty(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'alerts',
            '--alert-file',
            str(tmp_path / 'missing.jsonl'),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.stdout.strip() == '告警事件: 无'


def test_load_alert_events_rejects_invalid_json(tmp_path):
    alert_file = tmp_path / 'alerts.jsonl'
    alert_file.write_text('{bad json}', encoding='utf-8')

    with pytest.raises(ValueError, match='第 1 行不是合法 JSON'):
        cli_commands._load_alert_events(str(alert_file), limit=10)


def test_load_alert_events_rejects_negative_limit(tmp_path):
    alert_file = tmp_path / 'alerts.jsonl'
    _write_alerts(alert_file)

    with pytest.raises(ValueError, match='--limit 不能小于 0'):
        cli_commands._load_alert_events(str(alert_file), limit=-1)


def test_load_alert_events_uses_configured_default_path(tmp_path, monkeypatch):
    alert_file = tmp_path / 'configured-alerts.jsonl'
    events = _write_alerts(alert_file)
    monkeypatch.setitem(
        cli_commands.SYSTEM_CONFIG['monitor'],
        'alert_file_path',
        str(alert_file),
    )

    assert cli_commands._load_alert_events(None, limit=10) == events


def test_cmd_alerts_limit_zero_outputs_empty(tmp_path, capsys):
    alert_file = tmp_path / 'alerts.jsonl'
    _write_alerts(alert_file)

    cli_commands.cmd_alerts(SimpleNamespace(
        alert_file=str(alert_file),
        limit=0,
        json=False,
    ))

    assert capsys.readouterr().out.strip() == '告警事件: 无'
