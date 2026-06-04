import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from config.settings import SYSTEM_CONFIG
from config.validation import validate_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_cli_config_validate_default_config_passes():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'config',
            'validate',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.stdout.strip() == '配置校验: OK'


def test_cli_config_validate_json_outputs_structured_result():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'config',
            'validate',
            '--json',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    result = json.loads(completed.stdout)

    assert result == {
        'valid': True,
        'errors': [],
        'warnings': [],
    }


def test_cli_config_validate_file_reports_errors(tmp_path):
    config = deepcopy(SYSTEM_CONFIG)
    config['account']['initial_capital'] = 0
    config_path = tmp_path / 'bad-config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'config',
            'validate',
            '--config',
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 1
    assert '配置校验: FAIL' in completed.stdout
    assert '- account.initial_capital 必须大于 0' in completed.stdout


def test_cli_config_validate_file_rejects_non_finite_json_number(tmp_path):
    config = deepcopy(SYSTEM_CONFIG)
    config['account']['initial_capital'] = float('nan')
    config_path = tmp_path / 'nan-config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'config',
            'validate',
            '--config',
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 1
    assert '- account.initial_capital 必须大于 0' in completed.stdout


def test_validate_config_warns_for_real_adapter_mode():
    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data']['mode'] = 'real'

    result = validate_config(config)

    assert result['valid'] is True
    assert result['errors'] == []
    assert result['warnings'] == [
        'data.mx_data.mode=real 当前仍是未实现适配器',
    ]


def test_validate_config_rejects_invalid_adapter_mode():
    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data']['mode'] = 'paper'

    result = validate_config(config)

    assert result['valid'] is False
    assert 'data.mx_data.mode 必须是 mock 或 real' in result['errors']


def test_validate_config_rejects_invalid_risk_adapter_mode():
    config = deepcopy(SYSTEM_CONFIG)
    config['risk']['mx_data'] = {'mode': 'paper'}

    result = validate_config(config)

    assert result['valid'] is False
    assert 'risk.mx_data.mode 必须是 mock 或 real' in result['errors']


def test_validate_config_warns_for_analysis_real_adapter_mode():
    config = deepcopy(SYSTEM_CONFIG)
    config['analysis'] = {'jason_kb': {'mode': 'real'}}

    result = validate_config(config)

    assert result['valid'] is True
    assert result['errors'] == []
    assert result['warnings'] == [
        'analysis.jason_kb.mode=real 当前仍是未实现适配器',
    ]


def test_validate_config_rejects_non_finite_numbers():
    config = deepcopy(SYSTEM_CONFIG)
    config['account']['initial_capital'] = float('nan')
    config['monitor']['alert_threshold'] = float('inf')

    result = validate_config(config)

    assert result['valid'] is False
    assert 'account.initial_capital 必须大于 0' in result['errors']
    assert 'monitor.alert_threshold 必须是数字' in result['errors']


def test_validate_config_rejects_missing_required_section():
    config = deepcopy(SYSTEM_CONFIG)
    del config['risk']

    result = validate_config(config)

    assert result['valid'] is False
    assert result['errors'] == ['缺少配置段: risk']


def test_load_config_file_rejects_non_object_json(tmp_path):
    config_path = tmp_path / 'list-config.json'
    config_path.write_text('[]', encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'config',
            'validate',
            '--config',
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 2
    assert '配置文件顶层必须是 JSON object' in completed.stderr
