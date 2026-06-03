import json

from monitor.alert import AlertManager
from monitor.monitor import SystemMonitor


def test_alert_manager_records_structured_event():
    manager = AlertManager({})

    event = manager.send_alert(
        '测试告警',
        level='error',
        category='risk.test',
        payload={'symbol': '510300'},
    )

    assert event['message'] == '测试告警'
    assert event['level'] == 'error'
    assert event['category'] == 'risk.test'
    assert event['payload'] == {'symbol': '510300'}
    assert isinstance(event['timestamp'], str)
    assert manager.get_alert_history() == [event]


def test_alert_manager_writes_jsonl_file(tmp_path):
    alert_file = tmp_path / 'alerts' / 'events.jsonl'
    manager = AlertManager({'alert_file_path': str(alert_file)})

    manager.send_alert(
        '亏损告警',
        category='risk.pnl',
        payload={'pnl_percent': -12.5},
    )

    lines = alert_file.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event['message'] == '亏损告警'
    assert event['category'] == 'risk.pnl'
    assert event['payload'] == {'pnl_percent': -12.5}


def test_system_monitor_emits_pnl_and_position_alerts(tmp_path):
    alert_file = tmp_path / 'alerts.jsonl'
    monitor = SystemMonitor({
        'alert_threshold': -5,
        'max_position': 2,
        'alert_file_path': str(alert_file),
    })

    monitor.update_metrics(
        {
            'capital': 100000,
            'position_count': 2,
            'total_value': 93000,
            'pnl': -7000,
            'pnl_percent': -7,
        },
        {},
    )

    alerts = monitor.get_alert_history()
    assert [alert['category'] for alert in alerts] == [
        'risk.pnl',
        'risk.position',
    ]
    assert alerts[0]['payload'] == {'pnl_percent': -7, 'threshold': -5}
    assert alerts[1]['payload'] == {'position': 2, 'max_position': 2}
    assert len(alert_file.read_text(encoding='utf-8').splitlines()) == 2


def test_alert_history_limit_returns_latest_events():
    manager = AlertManager({})
    for index in range(3):
        manager.send_alert(f'告警 {index}')

    assert [event['message'] for event in manager.get_alert_history(limit=2)] == [
        '告警 1',
        '告警 2',
    ]


def test_alert_history_non_positive_limit_returns_empty():
    manager = AlertManager({})
    manager.send_alert('告警')

    assert manager.get_alert_history(limit=0) == []
    assert manager.get_alert_history(limit=-1) == []


def test_alert_file_write_failure_does_not_break_send_alert(monkeypatch, caplog):
    manager = AlertManager({'alert_file_path': 'alerts.jsonl'})

    def fail_open(*args, **kwargs):
        raise OSError('disk unavailable')

    monkeypatch.setattr('monitor.alert.Path.open', fail_open)

    event = manager.send_alert('落盘失败也要返回')

    assert event['message'] == '落盘失败也要返回'
    assert manager.get_alert_history() == [event]
    assert '告警写入 JSONL 失败' in caplog.text
