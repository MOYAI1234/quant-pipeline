import subprocess
import sys
from pathlib import Path

from monitor.report import ReportGenerator


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _health_statuses():
    return {
        'mx_data': {
            'service': 'MXDataAdapter',
            'mode': 'mock',
            'connected': True,
            'available': True,
            'mock': True,
            'error': '',
        },
        'mx_search': {
            'service': 'MX_SearchAdapter',
            'mode': 'real',
            'connected': False,
            'available': False,
            'mock': False,
            'error': 'real mode not implemented',
        },
    }


def test_daily_report_includes_data_health_section():
    report = ReportGenerator({}).generate_daily_report(
        {'capital': 100000, 'position_count': 0, 'total_value': 100000},
        {},
        _health_statuses(),
    )

    assert '## 数据源状态' in report
    assert '- 总体: FAIL (mixed/real)' in report
    assert '- mx_data: 可用, mode=mock' in report
    assert '- mx_search: 不可用, mode=real' in report


def test_cli_daily_report_includes_default_mock_data_health():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'report',
            '--type',
            'daily',
            '--no-state',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert '## 数据源状态' in completed.stdout
    assert '- 总体: OK (mock)' in completed.stdout
    assert '- mx_data: 可用, mode=mock' in completed.stdout
