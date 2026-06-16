import subprocess
import sys
from pathlib import Path

from main import QuantPipeline
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
        cache_policy={'history_ttl_seconds': 3600},
    )

    assert '## 数据源状态' in report
    assert '- 总体: FAIL (mixed/real)' in report
    assert '- 缓存: history_ttl_seconds=3600' in report
    assert 'history_hits=0' in report
    assert 'history_misses=0' in report
    assert 'last_history_hit=-' in report
    assert '- mx_data: 可用, mode=mock' in report
    assert '- mx_search: 不可用, mode=real' in report


def test_daily_report_includes_alert_events_when_provided():
    report = ReportGenerator({}).generate_daily_report(
        {'capital': 100000, 'position_count': 0, 'total_value': 100000},
        {},
        _health_statuses(),
        [
            {
                'level': 'warning',
                'category': 'risk.pnl',
                'message': '亏损告警: -12.00%',
                'timestamp': '2026-06-03T10:00:00',
            },
        ],
    )

    assert '## 告警事件' in report
    assert (
        '- [warning] risk.pnl: 亏损告警: -12.00% '
        '(2026-06-03T10:00:00)'
    ) in report


def test_daily_report_includes_empty_alert_section_when_no_alerts():
    report = ReportGenerator({}).generate_daily_report(
        {'capital': 100000, 'position_count': 0, 'total_value': 100000},
        {},
        _health_statuses(),
        [],
    )

    assert '## 告警事件' in report
    assert '- 无' in report


def test_weekly_report_includes_alert_events_when_provided():
    report = ReportGenerator({}).generate_weekly_report(
        {'total_value': 98000, 'pnl': -2000, 'pnl_percent': -2},
        {},
        _health_statuses(),
        [
            {
                'level': 'warning',
                'category': 'risk.position',
                'message': '持仓告警: 5格',
                'timestamp': '2026-06-03T10:30:00',
            },
        ],
    )

    assert '## 告警事件' in report
    assert (
        '- [warning] risk.position: 持仓告警: 5格 '
        '(2026-06-03T10:30:00)'
    ) in report


def test_daily_report_treats_empty_data_health_as_unavailable():
    report = ReportGenerator({}).generate_daily_report(
        {'capital': 100000, 'position_count': 0, 'total_value': 100000},
        {},
        {},
    )

    assert '## 数据源状态' in report
    assert '- 总体: FAIL (mixed/real)' in report


def test_generate_report_preserves_existing_data_connections():
    system = QuantPipeline()
    system.data_manager.connect()

    try:
        report = system.generate_report('daily')

        assert '## 数据源状态' in report
        assert system.data_manager.mx_data.connected is True
        assert system.data_manager.mx_xuangu.connected is True
        assert system.data_manager.mx_search.connected is True
    finally:
        system.data_manager.disconnect()


def test_generate_report_includes_monitor_alert_history():
    system = QuantPipeline()
    system.monitor.alert_manager.send_alert(
        '持仓告警: 5格',
        category='risk.position',
        payload={'position': 5, 'max_position': 5},
    )

    report = system.generate_report('daily')

    assert '## 告警事件' in report
    assert '- [warning] risk.position: 持仓告警: 5格' in report


def test_generate_report_includes_cache_policy():
    system = QuantPipeline()

    report = system.generate_report('daily')

    assert '## 数据源状态' in report
    assert '- 缓存: history_ttl_seconds=3600' in report
    assert 'history_hits=0' in report
    assert 'history_misses=0' in report


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
    assert '- 缓存: history_ttl_seconds=3600' in completed.stdout
    assert 'history_hits=0' in completed.stdout
    assert 'history_misses=0' in completed.stdout
    assert '- mx_data: 可用, mode=mock' in completed.stdout
