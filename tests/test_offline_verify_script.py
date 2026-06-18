import json
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
    assert 'backtest-artifacts:' in completed.stdout
    assert 'history-export-rotation-help:' in completed.stdout


def test_backtest_artifact_script_generates_verified_manifest(tmp_path):
    output_dir = tmp_path / 'artifacts'
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'verify_backtest_artifacts.py'),
            '--output-dir',
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert 'grid: 6 artifacts verified and reproducible' in completed.stdout
    assert 'rotation: 6 artifacts verified and reproducible' in completed.stdout
    manifest = json.loads(
        (output_dir / 'manifest.json').read_text(encoding='utf-8')
    )
    assert set(manifest['strategies']) == {'grid', 'rotation'}
    for strategy in ('grid', 'rotation'):
        artifacts = manifest['strategies'][strategy]
        assert set(artifacts) == {
            'report.md',
            'equity.csv',
            'portfolio.csv',
            'trades.csv',
            'positions.csv',
            'rejections.csv',
        }
        assert artifacts['equity.csv']['rows'] > 0
        assert len(artifacts['report.md']['sha256']) == 64
