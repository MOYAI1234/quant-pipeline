import importlib.util
from pathlib import Path

import pytest

from data.data_manager import DataManager


PROVIDER_PATH = (
    Path(__file__).resolve().parent.parent
    / 'examples'
    / 'providers'
    / 'akshare_history_provider.py'
)


def _load_provider_module():
    spec = importlib.util.spec_from_file_location(
        'akshare_history_provider',
        PROVIDER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_akshare_provider_normalizes_etf_history_rows_and_volume_lots():
    provider = _load_provider_module()

    rows = provider.normalize_akshare_records([
        {
            '日期': '20260102',
            '开盘': '4.10',
            '收盘': '4.20',
            '最高': '4.30',
            '最低': '4.00',
            '成交量': '1,100',
            '成交额': '4620.5',
        },
        {
            '日期': '2026-01-01',
            '开盘': 4.0,
            '收盘': 4.1,
            '最高': 4.2,
            '最低': 3.9,
            '成交量': 1000,
            '成交额': 4100,
        },
    ])

    assert rows == [
        {
            'date': '2026-01-01',
            'open': 4.0,
            'high': 4.2,
            'low': 3.9,
            'close': 4.1,
            'volume': 100000,
            'amount': 4100.0,
        },
        {
            'date': '2026-01-02',
            'open': 4.1,
            'high': 4.3,
            'low': 4.0,
            'close': 4.2,
            'volume': 110000,
            'amount': 4620.5,
        },
    ]


def test_akshare_provider_rejects_invalid_history_rows():
    provider = _load_provider_module()

    with pytest.raises(ValueError, match='field close must be numeric'):
        provider.normalize_akshare_records([
            {
                '日期': '2026-01-01',
                '开盘': 4.0,
                '收盘': '停牌',
                '最高': 4.2,
                '最低': 3.9,
                '成交量': 1000,
                '成交额': 4100,
            },
        ])


def test_akshare_provider_rejects_fractional_volume():
    provider = _load_provider_module()

    with pytest.raises(ValueError, match='field volume must be an integer'):
        provider.normalize_akshare_records([
            {
                '日期': '2026-01-01',
                '开盘': 4.0,
                '收盘': 4.1,
                '最高': 4.2,
                '最低': 3.9,
                '成交量': 1000.5,
                '成交额': 4100,
            },
        ])


def test_akshare_provider_rows_pass_data_manager_history_contract():
    provider = _load_provider_module()
    rows = provider.normalize_akshare_records([
        {
            '日期': '2026-01-01',
            '开盘': 4.0,
            '收盘': 4.1,
            '最高': 4.2,
            '最低': 3.9,
            '成交量': 1000.0,
            '成交额': 4100,
        },
    ])

    manager = DataManager({
        'mx_data': {'mode': 'mock'},
        'mx_xuangu': {'mode': 'mock'},
        'mx_search': {'mode': 'mock'},
    })
    manager.mx_data.get_etf_history = lambda *_args: rows

    history = manager.get_etf_history(
        '510300',
        '2026-01-01',
        '2026-01-01',
    )

    assert history[0]['volume'] == 100000
    assert isinstance(history[0]['volume'], int)


def test_akshare_provider_compacts_cli_dates():
    provider = _load_provider_module()

    assert provider._compact_date('2026-01-02') == '20260102'
    with pytest.raises(ValueError, match='expected YYYY-MM-DD'):
        provider._compact_date('20260102')
