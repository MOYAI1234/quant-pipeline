import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from data.data_manager import DataManager


PROVIDER_PATH = (
    Path(__file__).resolve().parent.parent
    / 'examples'
    / 'providers'
    / 'tushare_history_provider.py'
)


def _load_provider_module():
    spec = importlib.util.spec_from_file_location(
        'tushare_history_provider',
        PROVIDER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tushare_provider_normalizes_units_and_history_order():
    provider = _load_provider_module()

    rows = provider.normalize_tushare_records([
        {
            'trade_date': '20260102',
            'open': 4.1,
            'high': 4.3,
            'low': 4.0,
            'close': 4.2,
            'vol': 1100.5,
            'amount': 4620.5,
        },
        {
            'trade_date': '20260101',
            'open': 4.0,
            'high': 4.2,
            'low': 3.9,
            'close': 4.1,
            'vol': 1000,
            'amount': 4100,
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
            'amount': 4100000.0,
        },
        {
            'date': '2026-01-02',
            'open': 4.1,
            'high': 4.3,
            'low': 4.0,
            'close': 4.2,
            'volume': 110050,
            'amount': 4620500.0,
        },
    ]


@pytest.mark.parametrize(
    'symbol, expected',
    [
        ('510300', '510300.SH'),
        ('159915', '159915.SZ'),
        ('510300.SH', '510300.SH'),
        ('159915.sz', '159915.SZ'),
    ],
)
def test_tushare_provider_normalizes_etf_ts_code(symbol, expected):
    provider = _load_provider_module()

    assert provider._to_ts_code(symbol) == expected


def test_tushare_provider_rejects_invalid_symbol_and_volume():
    provider = _load_provider_module()

    for symbol in ('ETF510300', '600000', '510300.SZ'):
        with pytest.raises(ValueError, match='invalid TuShare ETF symbol'):
            provider._to_ts_code(symbol)
    with pytest.raises(ValueError, match='whole shares'):
        provider.normalize_tushare_records([{
            'trade_date': '20260101',
            'open': 4.0,
            'high': 4.2,
            'low': 3.9,
            'close': 4.1,
            'vol': 1.005,
            'amount': 4100,
        }])


def test_tushare_provider_converts_fractional_lots_without_float_artifacts():
    provider = _load_provider_module()

    rows = provider.normalize_tushare_records([{
        'trade_date': '20260101',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'vol': 1.11,
        'amount': 4100,
    }])

    assert rows[0]['volume'] == 111


def test_tushare_provider_requires_token_before_import(monkeypatch):
    provider = _load_provider_module()
    monkeypatch.delenv(provider.TUSHARE_TOKEN_ENV, raising=False)

    with pytest.raises(RuntimeError, match='TUSHARE_TOKEN'):
        provider.fetch_tushare_history(
            '510300',
            '2026-01-01',
            '2026-01-02',
        )


def test_tushare_provider_calls_fund_daily_with_token_and_fields(monkeypatch):
    provider = _load_provider_module()
    calls = {}

    class FakeFrame:
        def to_dict(self, orient):
            assert orient == 'records'
            return []

    class FakeClient:
        def fund_daily(self, **kwargs):
            calls['fund_daily'] = kwargs
            return FakeFrame()

    def fake_pro_api(token):
        calls['token'] = token
        return FakeClient()

    monkeypatch.setenv(provider.TUSHARE_TOKEN_ENV, 'local-secret')
    monkeypatch.setitem(
        sys.modules,
        'tushare',
        SimpleNamespace(pro_api=fake_pro_api),
    )

    rows = provider.fetch_tushare_history(
        '510300',
        '2026-01-01',
        '2026-01-02',
    )

    assert rows == []
    assert calls == {
        'token': 'local-secret',
        'fund_daily': {
            'ts_code': '510300.SH',
            'start_date': '20260101',
            'end_date': '20260102',
            'fields': 'trade_date,open,high,low,close,vol,amount',
        },
    }


def test_tushare_provider_applies_latest_normalized_qfq(monkeypatch):
    provider = _load_provider_module()

    class FakeFrame:
        def __init__(self, records):
            self.records = records

        def to_dict(self, orient):
            assert orient == 'records'
            return self.records

    class FakeClient:
        def fund_daily(self, **_kwargs):
            return FakeFrame([
                {
                    'trade_date': '20260101',
                    'open': 10,
                    'high': 10,
                    'low': 10,
                    'close': 10,
                    'vol': 1,
                    'amount': 1,
                },
                {
                    'trade_date': '20260102',
                    'open': 9,
                    'high': 9,
                    'low': 9,
                    'close': 9,
                    'vol': 1,
                    'amount': 1,
                },
            ])

        def fund_adj(self, **_kwargs):
            return FakeFrame([
                {'trade_date': '20260101', 'adj_factor': 1.0},
                {'trade_date': '20260102', 'adj_factor': 1.1},
            ])

    monkeypatch.setenv(provider.TUSHARE_TOKEN_ENV, 'local-secret')
    monkeypatch.setitem(
        sys.modules,
        'tushare',
        SimpleNamespace(pro_api=lambda _token: FakeClient()),
    )

    rows = provider.fetch_tushare_history(
        '511010',
        '2026-01-01',
        '2026-01-02',
        adjustment='qfq',
    )

    assert rows[0]['close'] == pytest.approx(10 / 1.1)
    assert rows[1]['close'] == pytest.approx(9.0)


def test_tushare_provider_qfq_requires_factor_for_every_bar():
    provider = _load_provider_module()

    with pytest.raises(RuntimeError, match='fund_adj missing trade dates'):
        provider.apply_qfq_adjustment(
            [{'trade_date': '20260101', 'open': 1, 'high': 1, 'low': 1, 'close': 1}],
            [],
        )


def test_tushare_provider_applies_api_url_override(monkeypatch):
    provider = _load_provider_module()
    client = SimpleNamespace()
    calls = {}

    def fake_pro_api(token):
        calls['token'] = token
        return client

    monkeypatch.setenv(provider.TUSHARE_TOKEN_ENV, 'local-secret')
    monkeypatch.setenv(provider.TUSHARE_API_URL_ENV, 'https://example.test')
    monkeypatch.setitem(
        sys.modules,
        'tushare',
        SimpleNamespace(pro_api=fake_pro_api),
    )

    resolved = provider._build_tushare_client(
        sys.modules['tushare'],
        'local-secret',
    )

    assert resolved is client
    assert calls == {'token': 'local-secret'}
    assert getattr(client, '_DataApi__http_url') == 'https://example.test'


def test_tushare_provider_rejects_invalid_api_url(monkeypatch):
    provider = _load_provider_module()

    monkeypatch.setenv(provider.TUSHARE_API_URL_ENV, 'fastapic.stockai888.top')

    with pytest.raises(ValueError, match='TUSHARE_API_URL'):
        provider._build_tushare_client(
            SimpleNamespace(pro_api=lambda _token: SimpleNamespace()),
            'local-secret',
        )


def test_tushare_provider_pages_long_date_ranges(monkeypatch):
    provider = _load_provider_module()
    calls = []

    class FakeFrame:
        def __init__(self, records):
            self._records = records

        def to_dict(self, orient):
            assert orient == 'records'
            return self._records

    class FakeClient:
        def fund_daily(self, **kwargs):
            calls.append(kwargs)
            return FakeFrame([{
                'trade_date': kwargs['start_date'],
                'open': 4.0,
                'high': 4.2,
                'low': 3.9,
                'close': 4.1,
                'vol': 1,
                'amount': 1,
            }])

    monkeypatch.setenv(provider.TUSHARE_TOKEN_ENV, 'local-secret')
    monkeypatch.setattr(provider, 'TUSHARE_HISTORY_PAGE_DAYS', 2)
    monkeypatch.setitem(
        sys.modules,
        'tushare',
        SimpleNamespace(pro_api=lambda _token: FakeClient()),
    )

    rows = provider.fetch_tushare_history(
        '510300',
        '2026-01-01',
        '2026-01-04',
    )

    assert [row['date'] for row in rows] == ['2026-01-01', '2026-01-03']
    assert calls == [
        {
            'ts_code': '510300.SH',
            'start_date': '20260101',
            'end_date': '20260102',
            'fields': provider.TUSHARE_HISTORY_FIELDS,
        },
        {
            'ts_code': '510300.SH',
            'start_date': '20260103',
            'end_date': '20260104',
            'fields': provider.TUSHARE_HISTORY_FIELDS,
        },
    ]


def test_tushare_provider_rejects_page_at_row_limit(monkeypatch):
    provider = _load_provider_module()

    class FakeFrame:
        def to_dict(self, orient):
            assert orient == 'records'
            return [{}, {}]

    class FakeClient:
        def fund_daily(self, **_kwargs):
            return FakeFrame()

    monkeypatch.setenv(provider.TUSHARE_TOKEN_ENV, 'local-secret')
    monkeypatch.setattr(provider, 'TUSHARE_FUND_DAILY_ROW_LIMIT', 2)
    monkeypatch.setitem(
        sys.modules,
        'tushare',
        SimpleNamespace(pro_api=lambda _token: FakeClient()),
    )

    with pytest.raises(RuntimeError, match='5000-row limit'):
        provider.fetch_tushare_history(
            '510300',
            '2026-01-01',
            '2026-01-02',
        )


def test_tushare_provider_rejects_adjustment_page_at_row_limit(monkeypatch):
    provider = _load_provider_module()

    class FakeFrame:
        def __init__(self, records):
            self.records = records

        def to_dict(self, orient):
            assert orient == 'records'
            return self.records

    class FakeClient:
        def fund_daily(self, **_kwargs):
            return FakeFrame([])

        def fund_adj(self, **_kwargs):
            return FakeFrame([{}, {}])

    monkeypatch.setenv(provider.TUSHARE_TOKEN_ENV, 'local-secret')
    monkeypatch.setattr(provider, 'TUSHARE_FUND_DAILY_ROW_LIMIT', 2)
    monkeypatch.setitem(
        sys.modules,
        'tushare',
        SimpleNamespace(pro_api=lambda _token: FakeClient()),
    )

    with pytest.raises(RuntimeError, match='fund_adj page reached'):
        provider.fetch_tushare_history(
            '511010',
            '2026-01-01',
            '2026-01-02',
            adjustment='qfq',
        )


def test_tushare_provider_rows_pass_data_manager_history_contract():
    provider = _load_provider_module()
    rows = provider.normalize_tushare_records([{
        'trade_date': '20260101',
        'open': 4.0,
        'high': 4.2,
        'low': 3.9,
        'close': 4.1,
        'vol': 1000,
        'amount': 4100,
    }])
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
    assert history[0]['amount'] == 4100000.0


def test_tushare_provider_compacts_cli_dates():
    provider = _load_provider_module()

    assert provider._compact_date('2026-01-02') == '20260102'
    with pytest.raises(ValueError, match='expected YYYY-MM-DD'):
        provider._compact_date('20260102')
