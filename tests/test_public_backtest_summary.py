import json
import subprocess
import sys

import pytest

from scripts.summarize_public_backtest import summarize_public_backtest


def _write_joinquant_csv(path):
    content = '\n'.join([
        '时间,基准收益,策略收益,当日盈利,当日亏损,当日买入,当日卖出,超额收益(%)',
        '2026-01-01 16:00:00,0,0,0,0,1000,0,0',
        '2026-01-02 16:00:00,8,10,0,0,0,-500,2',
        '2026-01-03 16:00:00,6,5,0,0,0,0,-1',
        '2026-01-04 16:00:00,12,20,0,0,200,0,8',
    ])
    path.write_bytes(content.encode('gbk'))


def test_summarize_public_backtest_reads_gbk_joinquant_export(tmp_path):
    csv_path = tmp_path / 'joinquant.csv'
    _write_joinquant_csv(csv_path)

    summary = summarize_public_backtest(
        csv_path,
        initial_capital=10000,
    )

    assert summary['start_date'] == '2026-01-01'
    assert summary['end_date'] == '2026-01-04'
    assert summary['trade_days'] == 4
    assert summary['calendar_days'] == 4
    assert summary['total_return'] == pytest.approx(0.20)
    assert summary['benchmark_return'] == pytest.approx(0.12)
    assert summary['max_drawdown'] == pytest.approx(1 - 1.05 / 1.10)
    assert summary['max_drawdown_start'] == '2026-01-02'
    assert summary['max_drawdown_end'] == '2026-01-03'
    assert summary['active_trade_days'] == 3
    assert summary['total_buy_amount'] == pytest.approx(1200)
    assert summary['total_sell_amount'] == pytest.approx(500)
    assert summary['turnover_over_initial'] == pytest.approx(0.17)


def test_summarize_public_backtest_rebases_date_ranges(tmp_path):
    csv_path = tmp_path / 'joinquant.csv'
    _write_joinquant_csv(csv_path)

    summary = summarize_public_backtest(
        csv_path,
        start_date='2026-01-02',
        end_date='2026-01-04',
        initial_capital=10000,
    )

    assert summary['start_date'] == '2026-01-02'
    assert summary['end_date'] == '2026-01-04'
    assert summary['total_return'] == pytest.approx(1.20 / 1.10 - 1)
    assert summary['benchmark_return'] == pytest.approx(1.12 / 1.08 - 1)
    assert summary['max_drawdown'] == pytest.approx(1 - 1.05 / 1.10)


def test_public_backtest_summary_cli_outputs_json(tmp_path):
    csv_path = tmp_path / 'joinquant.csv'
    _write_joinquant_csv(csv_path)

    completed = subprocess.run(
        [
            sys.executable,
            'scripts/summarize_public_backtest.py',
            '--input',
            str(csv_path),
            '--initial-capital',
            '10000',
            '--json',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary['total_return'] == pytest.approx(0.20)
    assert summary['active_trade_days'] == 3
