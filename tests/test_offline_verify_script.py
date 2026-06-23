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
    assert 'public-backtest-summary-help:' in completed.stdout
    assert 'history-export-rotation-help:' in completed.stdout


def test_tushare_proxy_verify_script_lists_live_drill_steps():
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'verify_tushare_proxy.py'),
            '--list',
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert 'tushare-live-test:' in completed.stdout
    assert 'history-probe:' in completed.stdout
    assert 'history-export-grid:' in completed.stdout
    assert 'history-export-rotation:' in completed.stdout
    assert 'grid-backtest-load:' in completed.stdout
    assert 'rotation-backtest-load:' in completed.stdout
    assert 'TUSHARE_TOKEN' not in completed.stdout


def test_tushare_proxy_verify_script_requires_local_env(monkeypatch):
    monkeypatch.delenv('TUSHARE_TOKEN', raising=False)
    monkeypatch.delenv('TUSHARE_API_URL', raising=False)

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'verify_tushare_proxy.py'),
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert completed.returncode == 2
    assert 'Missing required environment variables' in completed.stderr
    assert 'TUSHARE_TOKEN' in completed.stderr
    assert 'TUSHARE_API_URL' in completed.stderr


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
