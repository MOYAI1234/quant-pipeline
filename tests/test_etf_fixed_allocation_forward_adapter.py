from scripts.backtest_etf_fixed_allocation import (
    candidate_payload,
    run_fixed_allocation_backtest,
)
from scripts.run_fixed_allocation_intraday_signal import generate_payload


def _history() -> list[dict]:
    rows = [
        ("2026-01-02", 10.0, 10.0),
        ("2026-02-27", 12.0, 10.0),
        ("2026-03-02", 13.0, 10.0),
        ("2026-03-03", 14.0, 10.0),
    ]
    return [
        {
            "date": day,
            "symbols": {
                "510300": {"close": stock, "prices": [stock], "amount": 1_000_000},
                "511010": {"close": bond, "prices": [bond], "amount": 1_000_000},
            },
        }
        for day, stock, bond in rows
    ]


def test_fixed_allocation_opens_both_assets_and_rebalances_in_quarter_month():
    report, account = run_fixed_allocation_backtest(
        _history(),
        stock_symbol="510300",
        bond_symbol="511010",
    )
    candidate = candidate_payload(
        report,
        account,
        stock_weight=0.5,
        bond_weight=0.5,
    )

    assert {trade["symbol"] for trade in report.trades[:2]} == {"510300", "511010"}
    assert any(trade["date"] == "2026-03-02" for trade in report.trades)
    assert candidate["family"] == "fixed_stock_bond_allocation"
    assert candidate["max_drawdown"] >= 0


def test_intraday_adapter_does_not_signal_outside_rebalance_month():
    payload = generate_payload(
        _history()[:2],
        {"510300": {"price": 12.5}, "511010": {"price": 10.0}},
        stock_symbol="510300",
        bond_symbol="511010",
        observed_at="2026-07-22T14:00:00+08:00",
        official_history_date="2026-02-27",
    )

    assert payload["state"] == "NO_SIGNAL"
    assert payload["signals"] == []


def test_intraday_adapter_emits_side_on_first_trading_day_of_quarter_month():
    payload = generate_payload(
        _history()[:2],
        {"510300": {"price": 15.0}, "511010": {"price": 10.0}},
        stock_symbol="510300",
        bond_symbol="511010",
        observed_at="2026-03-02T09:31:00+08:00",
        official_history_date="2026-02-27",
    )

    assert payload["state"] == "SIGNAL"
    assert {signal["action"] for signal in payload["signals"]} == {"BUY", "SELL"}
    assert '"rebalance_due": true' in payload["signal_summary"]
