import csv
import json
from datetime import date, timedelta

from scripts.run_intraday_signal import main
from scripts.screen_etf_trend_candidates import _candidate_configs


def test_run_intraday_signal_replays_history_without_orders(tmp_path):
    history_path = tmp_path / "history.csv"
    prices = []
    start = date(2025, 1, 1)
    with history_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["date", "symbol", "close", "prices", "volume"])
        writer.writeheader()
        for index in range(150):
            prices.append(str(1 + index * 0.001))
            writer.writerow({
                "date": (start + timedelta(days=index)).isoformat(),
                "symbol": "510300",
                "close": prices[-1],
                "prices": "|".join(prices),
                "volume": "1000000",
            })

    candidate = _candidate_configs("510300", "daily_core_guard")[0].name
    quotes_path = tmp_path / "quotes.json"
    quotes_path.write_text(
        json.dumps({"510300": {"price": 1.2, "volume": 1000000, "amount": 1000000}}),
        encoding="utf-8",
    )
    output_path = tmp_path / "signal.json"

    assert main([
        "--history", str(history_path),
        "--etf-pool", "510300",
        "--factor-family", "daily_core_guard",
        "--candidate-name", candidate,
        "--official-history-date", (start + timedelta(days=149)).isoformat(),
        "--observed-at", "2026-01-01T14:00:00+08:00",
        "--quotes", str(quotes_path),
        "--output", str(output_path),
    ]) == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["provisional"] is True
    assert payload["official_history_date"] == "2025-05-30"
    assert payload["state"] in {"SIGNAL", "NO_SIGNAL"}
