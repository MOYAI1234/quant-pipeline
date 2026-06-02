import subprocess
import sys
from pathlib import Path

from execution.simulator import Simulator
from persistence.state_store import JsonStateStore


def test_cli_status_restores_account_from_state_path(tmp_path):
    state_path = tmp_path / 'state.json'
    simulator = Simulator({'initial_capital': 100000})
    simulator.execute_order({
        'action': 'buy',
        'symbol': '510300',
        'price': 4.0,
        'shares': 1000,
    })
    JsonStateStore(str(state_path)).save(simulator, {})

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'status',
            '--state-path',
            str(state_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert '持仓: 1' in completed.stdout
