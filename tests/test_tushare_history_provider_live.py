import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from config.settings import SYSTEM_CONFIG


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROVIDER_PATH = (
    PROJECT_ROOT / 'examples' / 'providers' / 'tushare_history_provider.py'
)
RUN_ENV = 'RUN_TUSHARE_LIVE'
TOKEN_ENV = 'TUSHARE_TOKEN'

pytestmark = pytest.mark.live_data


def test_tushare_provider_runs_through_history_probe(tmp_path):
    if os.getenv(RUN_ENV) != '1':
        pytest.skip(f'set {RUN_ENV}=1 to run the live TuShare provider test')
    if importlib.util.find_spec('tushare') is None:
        pytest.fail('install optional dependency with: pip install tushare')
    if not os.getenv(TOKEN_ENV):
        pytest.fail(f'set {TOKEN_ENV} before running the live TuShare test')

    config = deepcopy(SYSTEM_CONFIG)
    config['data']['mx_data'] = {
        'mode': 'real',
        'timeout': 60,
        'history_providers': [
            {
                'name': 'tushare',
                'command': [
                    sys.executable,
                    str(PROVIDER_PATH),
                    '--symbol',
                    '{symbol}',
                    '--start-date',
                    '{start_date}',
                    '--end-date',
                    '{end_date}',
                ],
                'required_env': [TOKEN_ENV],
            },
        ],
    }
    config_path = tmp_path / 'tushare-live-config.json'
    config_path.write_text(
        json.dumps(config, ensure_ascii=False),
        encoding='utf-8',
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
            '2024-01-02',
            '--end-date',
            '2024-01-05',
            '--json',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result['available'] is True
    assert result['symbol'] == '510300'
    assert result['row_count'] > 0
    assert '2024-01-02' <= result['first_date'] <= result['last_date']
    assert result['last_date'] <= '2024-01-05'
