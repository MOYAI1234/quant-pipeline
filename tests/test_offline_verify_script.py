import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_offline_verify_script_lists_release_checks():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'verify_offline.py'),
            '--list',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert 'compile:' in completed.stdout
    assert 'pytest:' in completed.stdout
    assert 'health:' in completed.stdout
    assert 'diagnose:' in completed.stdout
    assert 'grid-backtest:' in completed.stdout
    assert 'rotation-backtest:' in completed.stdout
    assert 'history-export-rotation-help:' in completed.stdout
