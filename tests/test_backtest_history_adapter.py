import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from config.settings import SYSTEM_CONFIG

from backtest.history_adapter import (
    build_rotation_history,
    fetch_grid_history,
    fetch_rotation_history,
    normalize_grid_history,
    write_grid_history_csv,
    write_rotation_history_csv,
)
from backtest.runner import load_history_csv, load_rotation_history_csv


def _history(close_values):
    return [
        {
            'date': f'2026-01-0{index}',
            'open': close - 0.1,
            'high': close + 0.2,
            'low': close - 0.2,
            'close': close,
            'volume': 1000000 + index,
            'amount': close * 1000000,
        }
        for index, close in enumerate(close_values, start=1)
    ]


class FakeHistoryDataManager:

    def __init__(self, histories):
        self.histories = histories

    def get_etf_history(self, symbol: str, start_date: str, end_date: str) -> list:
        assert start_date == '2026-01-01'
        assert end_date == '2026-01-03'
        return self.histories[symbol]


def test_normalize_grid_history_preserves_backtest_csv_schema():
    rows = normalize_grid_history(_history([4.0, 4.1]))

    assert list(rows[0]) == [
        'date',
        'open',
        'high',
        'low',
        'close',
        'volume',
        'amount',
    ]
    assert rows[0]['date'] == '2026-01-01'
    assert rows[0]['open'] == pytest.approx(3.9)
    assert rows[0]['high'] == pytest.approx(4.2)
    assert rows[0]['low'] == pytest.approx(3.8)
    assert rows[0]['close'] == pytest.approx(4.0)
    assert rows[0]['volume'] == 1000001
    assert rows[0]['amount'] == pytest.approx(4000000.0)
    assert rows[1]['date'] == '2026-01-02'
    assert rows[1]['close'] == pytest.approx(4.1)
    assert rows[1]['amount'] == pytest.approx(4100000.0)


def test_write_grid_history_csv_can_be_loaded_by_backtest_runner(tmp_path):
    output_file = tmp_path / 'grid-history.csv'

    write_grid_history_csv(str(output_file), _history([4.0, 4.1]))

    rows = load_history_csv(str(output_file))
    assert [row['date'] for row in rows] == ['2026-01-01', '2026-01-02']
    assert rows[0]['close'] == pytest.approx(4.0)


def test_build_rotation_history_uses_rolling_prices_and_aligned_dates():
    history = build_rotation_history(
        {
            '510300': _history([10.0, 11.0, 12.0]),
            '510500': _history([8.0, 8.5, 9.0]),
        },
        lookback=2,
    )

    assert history[0]['symbols']['510300']['prices'] == [10.0]
    assert history[1]['symbols']['510300']['prices'] == [10.0, 11.0]
    assert history[2]['symbols']['510300']['prices'] == [11.0, 12.0]
    assert history[2]['symbols']['510500']['close'] == 9.0
    assert history[2]['symbols']['510500']['volume'] == 1000003


def test_build_rotation_history_rejects_misaligned_dates():
    symbol_history = _history([10.0, 11.0])
    misaligned_history = _history([8.0, 8.5])
    misaligned_history[1]['date'] = '2026-01-03'

    with pytest.raises(ValueError, match='轮动历史日期序列不一致: 510500'):
        build_rotation_history({
            '510300': symbol_history,
            '510500': misaligned_history,
        })


def test_build_rotation_history_rejects_duplicate_symbols_after_trim():
    with pytest.raises(ValueError, match='轮动历史 symbol 重复: 510300'):
        build_rotation_history({
            '510300': _history([10.0, 11.0]),
            ' 510300 ': _history([8.0, 8.5]),
        })


def test_normalize_grid_history_rejects_non_finite_numbers():
    history = _history([4.0])
    history[0]['close'] = float('nan')

    with pytest.raises(ValueError, match='字段 close 不是有限数字'):
        normalize_grid_history(history)


def test_write_rotation_history_csv_can_be_loaded_by_backtest_runner(tmp_path):
    output_file = tmp_path / 'rotation-history.csv'
    history = build_rotation_history(
        {
            '510300': _history([10.0, 11.0]),
            '510500': _history([8.0, 8.5]),
        },
        lookback=2,
    )

    write_rotation_history_csv(str(output_file), history)

    rows = load_rotation_history_csv(str(output_file))
    assert rows[1]['symbols']['510300']['prices'] == [10.0, 11.0]
    assert rows[1]['symbols']['510500']['close'] == pytest.approx(8.5)


def test_fetch_history_helpers_use_data_manager_contract():
    manager = FakeHistoryDataManager({
        '510300': _history([10.0, 11.0, 12.0]),
        '510500': _history([8.0, 8.5, 9.0]),
    })

    grid_history = fetch_grid_history(
        manager,
        '510300',
        '2026-01-01',
        '2026-01-03',
    )
    rotation_history = fetch_rotation_history(
        manager,
        ['510300', '510500'],
        '2026-01-01',
        '2026-01-03',
        lookback=2,
    )

    assert grid_history[-1]['close'] == pytest.approx(12.0)
    assert rotation_history[-1]['symbols']['510500']['prices'] == [8.5, 9.0]


def test_cli_history_export_grid_from_json(tmp_path):
    input_file = tmp_path / 'grid-history.json'
    output_file = tmp_path / 'grid-history.csv'
    input_file.write_text(json.dumps(_history([4.0, 4.1])), encoding='utf-8')

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'history',
            'export-grid',
            '--input-json',
            str(input_file),
            '--output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'grid 历史 CSV: {output_file}' in completed.stdout
    assert load_history_csv(str(output_file))[1]['close'] == pytest.approx(4.1)


def test_cli_history_export_grid_from_real_history_provider_config(tmp_path):
    provider = tmp_path / 'history_provider.py'
    provider.write_text(
        """
import json
import sys

assert sys.argv[1:] == ['510300', '2026-01-01', '2026-01-02']
print(json.dumps([
    {
        'date': '2026-01-01',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'volume': 1000,
        'amount': 4100.0,
    },
    {
        'date': '2026-01-02',
        'open': 4.1,
        'high': 4.3,
        'low': 4.0,
        'close': 4.2,
        'volume': 1100,
        'amount': 4620.0,
    },
]))
""".strip(),
        encoding='utf-8',
    )
    config = json.loads(json.dumps(SYSTEM_CONFIG))
    config['data']['mx_data'] = {
        'mode': 'real',
        'timeout': 10,
        'history_command': [
            sys.executable,
            str(provider),
            '{symbol}',
            '{start_date}',
            '{end_date}',
        ],
    }
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    output_file = tmp_path / 'grid-history.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'history',
            'export-grid',
            '--config',
            str(config_path),
            '--symbol',
            '510300',
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'grid 历史 CSV: {output_file}' in completed.stdout
    rows = load_history_csv(str(output_file))
    assert rows[0]['close'] == pytest.approx(4.1)
    assert rows[1]['volume'] == 1100


def test_cli_history_export_reports_provider_errors_without_traceback(tmp_path):
    provider = tmp_path / 'bad_history_provider.py'
    provider.write_text("print('not-json')", encoding='utf-8')
    config = json.loads(json.dumps(SYSTEM_CONFIG))
    config['data']['mx_data'] = {
        'mode': 'real',
        'timeout': 10,
        'history_command': [
            sys.executable,
            str(provider),
            '{symbol}',
            '{start_date}',
            '{end_date}',
        ],
    }
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    output_file = tmp_path / 'grid-history.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'history',
            'export-grid',
            '--config',
            str(config_path),
            '--symbol',
            '510300',
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--output',
            str(output_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert 'MXDataAdapter history provider output is not valid JSON' in completed.stderr
    assert 'Traceback' not in completed.stderr


def test_cli_history_export_rejects_non_object_data_config(tmp_path):
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps({'data': []}), encoding='utf-8')
    output_file = tmp_path / 'grid-history.csv'

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'history',
            'export-grid',
            '--config',
            str(config_path),
            '--start-date',
            '2026-01-01',
            '--end-date',
            '2026-01-02',
            '--output',
            str(output_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert '配置文件缺少 data 对象' in completed.stderr
    assert 'Traceback' not in completed.stderr


def test_cli_history_export_rotation_from_json(tmp_path):
    input_file = tmp_path / 'rotation-history.json'
    output_file = tmp_path / 'rotation-history.csv'
    input_file.write_text(
        json.dumps({
            '510300': _history([10.0, 11.0, 12.0]),
            '510500': _history([8.0, 8.5, 9.0]),
        }),
        encoding='utf-8',
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(Path('cli') / 'commands.py'),
            'history',
            'export-rotation',
            '--input-json',
            str(input_file),
            '--lookback',
            '2',
            '--output',
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f'rotation 历史 CSV: {output_file}' in completed.stdout
    with output_file.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert rows[-2]['symbol'] == '510300'
    assert rows[-2]['prices'] == '11.0|12.0'
    assert load_rotation_history_csv(str(output_file))[-1]['symbols']['510500'][
        'prices'
    ] == [8.5, 9.0]
