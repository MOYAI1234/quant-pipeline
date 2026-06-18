import json
import os
import subprocess
import sys
from pathlib import Path

from config.validation import validate_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = (
    PROJECT_ROOT
    / 'examples'
    / 'configs'
    / 'history-providers.local.example.json'
)


def test_history_provider_example_config_validates_without_secrets(monkeypatch):
    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    config = json.loads(EXAMPLE_CONFIG.read_text(encoding='utf-8'))

    result = validate_config(config)

    assert result['valid'] is True
    assert result['errors'] == []
    assert config['data']['mx_data']['history_retry_delay_seconds'] == 30
    assert (
        'data.mx_data.history_providers[0].required_env '
        '缺少环境变量: TUSHARE_TOKEN'
    ) in result['warnings']


def test_health_config_reports_provider_readiness_without_network(monkeypatch):
    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    env = os.environ.copy()
    env.pop('TUSHARE_TOKEN', None)

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'cli' / 'commands.py'),
            'health',
            '--config',
            str(EXAMPLE_CONFIG),
            '--no-state',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
    )

    assert '- mx_data: 不可用, mode=real' in completed.stdout
    assert (
        '- mx_data history providers: '
        'tushare missing_env=TUSHARE_TOKEN; akshare ready'
    ) in completed.stdout
