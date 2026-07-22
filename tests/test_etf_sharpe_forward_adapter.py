from scripts.backtest_etf_sharpe_rotation import (
    candidate_payload,
    run_sharpe_backtest,
)
from scripts.run_sharpe_intraday_signal import generate_payload


def _history(days: int = 184) -> list[dict]:
    history = []
    for index in range(days):
        rising = [100 + offset for offset in range(index + 1)]
        falling = [200 - offset * 0.2 for offset in range(index + 1)]
        history.append({
            "date": f"2026-{1 + index // 28:02d}-{1 + index % 28:02d}",
            "symbols": {
                "510300": {
                    "close": rising[-1],
                    "prices": rising,
                    "amount": 1_000_000,
                },
                "510500": {
                    "close": falling[-1],
                    "prices": falling,
                    "amount": 1_000_000,
                },
            },
        })
    return history


def test_exact_sharpe_backtest_waits_for_180th_day():
    report, account, _ = run_sharpe_backtest(
        _history(180),
        momentum_window=60,
        volatility_window=60,
        min_history_days=120,
        warmup_days=180,
    )

    candidate = candidate_payload(report, account)

    assert report.trades[0]["date"] == _history(180)[-1]["date"]
    assert report.trades[0]["symbol"] == "510300"
    assert candidate["family"] == "sharpe_rotation"
    assert candidate["max_drawdown"] >= 0


def test_intraday_adapter_does_not_rebalance_off_schedule():
    history = _history(183)
    payload = generate_payload(
        history,
        {
            "510300": {"price": 284},
            "510500": {"price": 163.2},
        },
        observed_at="2026-07-10T14:00:00+08:00",
        official_history_date="2026-07-09",
        momentum_window=60,
        volatility_window=60,
        warmup_days=180,
    )

    assert payload["state"] == "NO_SIGNAL"
    assert payload["signals"] == []
    assert '"rebalance_due": false' in payload["signal_summary"]


def test_intraday_adapter_emits_model_actions_on_rebalance_day():
    history = _history(184)
    payload = generate_payload(
        history,
        {
            "510300": {"price": 285},
            "510500": {"price": 163.0},
        },
        observed_at="2026-07-10T14:00:00+08:00",
        official_history_date="2026-07-09",
        momentum_window=60,
        volatility_window=60,
        warmup_days=180,
    )

    assert payload["state"] == "SIGNAL"
    assert {item["action"] for item in payload["signals"]} <= {
        "BUY",
        "SELL",
        "REBALANCE",
    }
    assert '"rebalance_due": true' in payload["signal_summary"]
