import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from config.settings import SYSTEM_CONFIG


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cli_diagnose_outputs_readiness_summary():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--no-state',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert '运行诊断: OK' in completed.stdout
    assert '配置校验: OK' in completed.stdout
    assert '数据源状态: OK (mock)' in completed.stdout
    assert '状态文件: OK (disabled)' in completed.stdout


def test_cli_diagnose_json_outputs_structured_report(tmp_path):
    state_path = tmp_path / 'state.json'

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--json',
            '--state-path',
            str(state_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    report = json.loads(completed.stdout)

    assert report['ready'] is True
    assert report['config']['valid'] is True
    assert report['data']['available'] is True
    assert report['data']['cache']['history_ttl_seconds'] == 3600
    assert report['state']['ok'] is True
    assert report['state']['exists'] is False
    assert report['state']['has_data'] is False
    assert report['state']['path'] == str(state_path)


def test_cli_diagnose_strict_fails_invalid_config(tmp_path):
    config = deepcopy(SYSTEM_CONFIG)
    config['account']['initial_capital'] = 0
    config_path = tmp_path / 'bad-config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--config',
            str(config_path),
            '--strict',
            '--no-state',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 1
    assert '运行诊断: FAIL' in completed.stdout
    assert '- account.initial_capital 必须大于 0' in completed.stdout
    assert 'Traceback' not in completed.stderr


def test_cli_diagnose_reports_invalid_adapter_mode_without_traceback(tmp_path):
    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data']['mode'] = 'paper'
    config_path = tmp_path / 'bad-adapter-config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--config',
            str(config_path),
            '--strict',
            '--no-state',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 1
    assert '运行诊断: FAIL' in completed.stdout
    assert '- data.mx_data.mode 必须是 mock 或 real' in completed.stdout
    assert '- error: 不支持的适配器模式: paper' in completed.stdout
    assert 'Traceback' not in completed.stderr


def test_cli_diagnose_reports_malformed_config_sections_without_traceback(tmp_path):
    for section in ('data', 'state'):
        config = deepcopy(SYSTEM_CONFIG)
        config[section] = []
        config_path = tmp_path / f'bad-{section}-config.json'
        config_path.write_text(json.dumps(config), encoding='utf-8')

        completed = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / 'cli' / 'commands.py'),
                'diagnose',
                '--config',
                str(config_path),
                '--strict',
                '--no-state',
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        assert completed.returncode == 1
        assert '运行诊断: FAIL' in completed.stdout
        assert f'- {section} 必须是 dict' in completed.stdout
        assert 'Traceback' not in completed.stderr


def test_cli_diagnose_distinguishes_empty_existing_state_file(tmp_path):
    state_path = tmp_path / 'state.json'
    state_path.write_text('{}', encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--json',
            '--state-path',
            str(state_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    report = json.loads(completed.stdout)

    assert report['state']['exists'] is True
    assert report['state']['has_data'] is False
    assert report['state']['version'] == 1

    text_completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--state-path',
            str(state_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert '状态文件: OK (empty)' in text_completed.stdout


def test_cli_diagnose_strict_fails_invalid_state_file(tmp_path):
    state_path = tmp_path / 'state.json'
    state_path.write_text('{bad json', encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'diagnose',
            '--strict',
            '--state-path',
            str(state_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 1
    assert '运行诊断: FAIL' in completed.stdout
    assert '状态文件: FAIL' in completed.stdout
    assert 'Traceback' not in completed.stderr
