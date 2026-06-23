import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


ENCODINGS = ('utf-8-sig', 'utf-8', 'gbk', 'gb18030')
REQUIRED_COLUMNS = {
    '时间',
    '基准收益',
    '策略收益',
    '当日买入',
    '当日卖出',
}


@dataclass(frozen=True)
class PublicBacktestRow:
    date: str
    benchmark_return: float
    strategy_return: float
    buy_amount: float
    sell_amount: float


def summarize_public_backtest(
    csv_path: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_capital: float = 100000.0,
) -> dict:
    all_rows = _read_joinquant_rows(csv_path)
    rows = [
        row for row in all_rows
        if _in_range(row.date, start_date, end_date)
    ]
    if not rows:
        raise ValueError('no rows matched the requested date range')

    first = rows[0]
    last = rows[-1]
    base_row = _previous_row(all_rows, first.date) if start_date else None
    strategy_base = 1.0 + base_row.strategy_return if base_row else 1.0
    benchmark_base = 1.0 + base_row.benchmark_return if base_row else 1.0
    base_date = base_row.date if base_row else first.date
    trade_days = len(rows)
    calendar_days = _calendar_days(first.date, last.date)
    total_return = _period_return(last.strategy_return, strategy_base)
    benchmark_return = _period_return(last.benchmark_return, benchmark_base)
    annual_return = _annualized_return(total_return, calendar_days)
    max_drawdown, drawdown_start, drawdown_end = _drawdown_stats(
        rows,
        strategy_base=strategy_base,
        base_date=base_date,
    )
    total_buy_amount = sum(row.buy_amount for row in rows)
    total_sell_amount = sum(abs(row.sell_amount) for row in rows)
    turnover = total_buy_amount + total_sell_amount
    annual_turnover = _annualized_turnover(
        turnover,
        initial_capital,
        calendar_days,
    )

    return {
        'source': str(csv_path),
        'start_date': first.date,
        'end_date': last.date,
        'trade_days': trade_days,
        'calendar_days': calendar_days,
        'initial_capital': initial_capital,
        'total_return': total_return,
        'annual_return': annual_return,
        'benchmark_return': benchmark_return,
        'excess_return': total_return - benchmark_return,
        'max_drawdown': max_drawdown,
        'max_drawdown_start': drawdown_start,
        'max_drawdown_end': drawdown_end,
        'active_trade_days': sum(
            1 for row in rows
            if row.buy_amount > 0 or row.sell_amount != 0
        ),
        'total_buy_amount': total_buy_amount,
        'total_sell_amount': total_sell_amount,
        'turnover': turnover,
        'turnover_over_initial': _safe_ratio(turnover, initial_capital),
        'annual_turnover_over_initial': annual_turnover,
    }


def _read_joinquant_rows(csv_path: Path) -> list[PublicBacktestRow]:
    content = _open_text(csv_path)
    reader = csv.DictReader(content.splitlines())
    fieldnames = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - fieldnames)
    if missing:
        raise ValueError(
            f"missing required JoinQuant columns: {', '.join(missing)}"
        )
    rows = [
        PublicBacktestRow(
            date=_parse_date(raw['时间']),
            benchmark_return=_parse_percent(raw['基准收益']),
            strategy_return=_parse_percent(raw['策略收益']),
            buy_amount=max(_parse_amount(raw['当日买入']), 0.0),
            sell_amount=_parse_amount(raw['当日卖出']),
        )
        for raw in reader
    ]
    rows.sort(key=lambda row: row.date)
    return rows


def _open_text(csv_path: Path) -> str:
    data = csv_path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(
        'public_backtest',
        data,
        0,
        min(len(data), 1),
        f"unsupported encoding; tried {', '.join(ENCODINGS)}",
    )


def _parse_date(value: str) -> str:
    text = value.strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    raise ValueError(f'invalid date: {value}')


def _parse_percent(value: str) -> float:
    return _parse_amount(value) / 100.0


def _parse_amount(value: str) -> float:
    text = str(value).strip().replace(',', '')
    if not text:
        return 0.0
    return float(text)


def _in_range(
    date: str,
    start_date: str | None,
    end_date: str | None,
) -> bool:
    if start_date and date < start_date:
        return False
    if end_date and date > end_date:
        return False
    return True


def _previous_row(
    rows: list[PublicBacktestRow],
    date_value: str,
) -> PublicBacktestRow | None:
    previous = None
    for row in rows:
        if row.date >= date_value:
            return previous
        previous = row
    return previous


def _annualized_return(total_return: float, calendar_days: int) -> float:
    if calendar_days <= 0 or total_return <= -1.0:
        return math.nan
    return (1.0 + total_return) ** (365.25 / calendar_days) - 1.0


def _period_return(cumulative_return: float, base_value: float) -> float:
    if base_value <= 0:
        return math.nan
    return (1.0 + cumulative_return) / base_value - 1.0


def _annualized_turnover(
    turnover: float,
    initial_capital: float,
    calendar_days: int,
) -> float:
    if calendar_days <= 0:
        return math.nan
    return _safe_ratio(turnover, initial_capital) * 365.25 / calendar_days


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return math.nan
    return numerator / denominator


def _calendar_days(start_date: str, end_date: str) -> int:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return (end - start).days + 1


def _drawdown_stats(
    rows: list[PublicBacktestRow],
    *,
    strategy_base: float,
    base_date: str,
) -> tuple[float, str, str]:
    peak_value = strategy_base
    peak_date = base_date
    max_drawdown = 0.0
    max_start = rows[0].date
    max_end = rows[0].date

    for row in rows:
        value = 1.0 + row.strategy_return
        if value > peak_value:
            peak_value = value
            peak_date = row.date
        drawdown = 0.0 if peak_value <= 0 else 1.0 - value / peak_value
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_start = peak_date
            max_end = row.date
    return max_drawdown, max_start, max_end


def _format_markdown(summary: dict) -> str:
    return '\n'.join([
        '# 公开平台回测摘要',
        '',
        f"- 来源: {summary['source']}",
        f"- 区间: {summary['start_date']} 至 {summary['end_date']}",
        f"- 交易日: {summary['trade_days']}",
        f"- 自然日: {summary['calendar_days']}",
        f"- 初始资金: {summary['initial_capital']:.2f}",
        f"- 策略总收益: {summary['total_return']:.2%}",
        f"- 策略年化: {summary['annual_return']:.2%}",
        f"- 基准总收益: {summary['benchmark_return']:.2%}",
        f"- 超额收益: {summary['excess_return']:.2%}",
        (
            f"- 最大回撤: {summary['max_drawdown']:.2%} "
            f"({summary['max_drawdown_start']} 至 "
            f"{summary['max_drawdown_end']})"
        ),
        f"- 有交易日期: {summary['active_trade_days']}",
        f"- 总买入金额: {summary['total_buy_amount']:.2f}",
        f"- 总卖出金额: {summary['total_sell_amount']:.2f}",
        f"- 总成交额/初始资金: {summary['turnover_over_initial']:.2%}",
        (
            f"- 年化成交额/初始资金: "
            f"{summary['annual_turnover_over_initial']:.2%}"
        ),
    ])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Summarize JoinQuant-style public backtest CSV exports.',
    )
    parser.add_argument('--input', required=True, help='公开平台导出的 CSV 路径')
    parser.add_argument('--start-date', help='统计起始日期，格式 YYYY-MM-DD')
    parser.add_argument('--end-date', help='统计结束日期，格式 YYYY-MM-DD')
    parser.add_argument('--initial-capital', type=float, default=100000.0)
    parser.add_argument(
        '--json',
        action='store_true',
        help='输出 JSON，默认输出 Markdown 摘要',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = summarize_public_backtest(
        Path(args.input),
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(_format_markdown(summary))


if __name__ == '__main__':
    main()
