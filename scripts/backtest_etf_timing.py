#!/usr/bin/env python3
"""510300 单ETF择时因子回测对比脚本。

测试多个择时因子在同一时间段的表现，输出对比报告。

用法:
  python scripts/backtest_etf_timing.py --history data/history/510300_history.csv
  python scripts/backtest_etf_timing.py --history data/history/510300_history.csv --factors CHOP-FILTER,ADX-TREND,RSI-MREV
"""

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_timing_factors import FACTOR_REGISTRY


# --- Config ---

@dataclass
class TimingBacktestConfig:
    initial_capital: float = 100000
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    slippage_rate: float = 0.001
    min_history_bars: int = 60  # 因子计算需要的最少历史K线


# --- Single ETF Backtest Engine ---

@dataclass
class TimingBacktestReport:
    factor_name: str
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float
    win_rate: float
    trade_count: int
    long_days: int
    cash_days: int
    equity_curve: list[dict]
    signals: list[dict]
    
    def summary_dict(self) -> dict:
        return {
            "factor": self.factor_name,
            "total_return": round(self.total_return, 4),
            "annual_return": round(self.annual_return, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "win_rate": round(self.win_rate, 4),
            "trade_count": self.trade_count,
            "long_days": self.long_days,
            "cash_days": self.cash_days,
        }


def run_timing_backtest(
    bars: list[dict],
    factor_fn,
    factor_name: str,
    config: TimingBacktestConfig,
) -> TimingBacktestReport:
    """单ETF择时回测引擎。
    
    状态: POSITION_FLAT(空仓) / POSITION_LONG(持仓)
    信号: 1=做多, 0=平仓/空仓, -1=保持
    
    每次生成1→做多或0→平仓的信号时执行交易，
    -1表示维持当前状态不变。
    """
    cash = config.initial_capital
    shares = 0
    position = 'FLAT'  # FLAT or LONG
    
    equity_curve = []
    signals_log = []
    trades = []
    
    for i in range(config.min_history_bars, len(bars)):
        bar = bars[i]
        date = bar['date']
        price = bar['close']
        hist_bars = bars[:i+1]  # 包含当天在内的所有历史
        
        # 计算因子信号
        result = factor_fn(hist_bars)
        signal = result.get('signal', 0)
        
        signals_log.append({
            'date': date,
            'signal': signal,
            'reason': result.get('reason', ''),
            'price': price,
        })
        
        # 交易逻辑
        if signal == 1 and position == 'FLAT':
            # 入场做多
            buy_price = price * (1 + config.slippage_rate)
            max_shares = int(cash / (buy_price * (1 + config.commission_rate)) / 100) * 100
            if max_shares > 0:
                cost = max_shares * buy_price
                commission = max(cost * config.commission_rate, config.min_commission)
                if cost + commission <= cash:
                    cash -= (cost + commission)
                    shares = max_shares
                    position = 'LONG'
                    trades.append({
                        'date': date,
                        'action': 'BUY',
                        'price': buy_price,
                        'shares': shares,
                        'amount': cost,
                        'commission': commission,
                    })
        
        elif signal == 0 and position == 'LONG':
            # 平仓
            sell_price = price * (1 - config.slippage_rate)
            proceeds = shares * sell_price
            commission = max(proceeds * config.commission_rate, config.min_commission)
            cash += proceeds - commission
            trades.append({
                'date': date,
                'action': 'SELL',
                'price': sell_price,
                'shares': shares,
                'amount': proceeds,
                'commission': commission,
                'profit': proceeds - trades[-1]['amount'] if trades and trades[-1]['action'] == 'BUY' else 0,
            })
            shares = 0
            position = 'FLAT'
        
        # 记录净值
        positions_value = shares * price
        total_value = cash + positions_value
        
        prev_value = config.initial_capital
        if equity_curve:
            prev_value = equity_curve[-1]['total_value']
        
        period_return = (total_value - prev_value) / prev_value if prev_value > 0 else 0
        
        peak = max(p['total_value'] for p in equity_curve) if equity_curve else total_value
        peak = max(peak, total_value)
        drawdown = (total_value - peak) / peak if peak > 0 else 0
        
        equity_curve.append({
            'date': date,
            'cash': cash,
            'positions_value': positions_value,
            'total_value': total_value,
            'period_return': period_return,
            'drawdown': drawdown,
        })
    
    # 绩效计算
    return _compute_timing_performance(
        factor_name, equity_curve, trades, signals_log, config
    )


def _compute_timing_performance(
    factor_name: str,
    equity_curve: list[dict],
    trades: list[dict],
    signals: list[dict],
    config: TimingBacktestConfig,
) -> TimingBacktestReport:
    if not equity_curve:
        return TimingBacktestReport(
            factor_name=factor_name, total_return=0, annual_return=0,
            max_drawdown=0, sharpe_ratio=0, calmar_ratio=0,
            win_rate=0, trade_count=0, long_days=0, cash_days=0,
            equity_curve=[], signals=[],
        )
    
    final_value = equity_curve[-1]['total_value']
    total_return = (final_value - config.initial_capital) / config.initial_capital
    
    days = len(equity_curve)
    years = days / 252
    annual_return = (final_value / config.initial_capital) ** (1 / max(years, 0.01)) - 1
    
    max_dd = min(p['drawdown'] for p in equity_curve)
    
    daily_returns = [p['period_return'] for p in equity_curve]
    if len(daily_returns) > 1:
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_ret = math.sqrt(variance)
        sharpe = (mean_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0
    else:
        sharpe = 0
    
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0
    
    # 统计胜率 (按完整交易回合)
    buy_trades = [t for t in trades if t['action'] == 'BUY']
    sell_trades = [t for t in trades if t['action'] == 'SELL']
    profitable_trades = sum(1 for t in sell_trades if t.get('profit', 0) > 0)
    win_rate = profitable_trades / len(sell_trades) if sell_trades else 0
    
    trade_count = len(trades)
    
    # 持仓/空仓天数
    long_days = sum(1 for p in equity_curve if p['positions_value'] > 100)
    cash_days = len(equity_curve) - long_days
    
    return TimingBacktestReport(
        factor_name=factor_name,
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        win_rate=win_rate,
        trade_count=trade_count,
        long_days=long_days,
        cash_days=cash_days,
        equity_curve=equity_curve,
        signals=signals,
    )


# --- Load CSV ---

def load_ohlcv_csv(path: str) -> list[dict]:
    """加载标准OHLCV CSV (date, open, high, low, close, volume, amount)。"""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV不存在: {csv_path}")
    
    bars = []
    with csv_path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                'date': row.get('date', ''),
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'close': float(row.get('close', 0)),
                'volume': float(row.get('volume', 0)),
                'amount': float(row.get('amount', 0)),
            })
    
    bars.sort(key=lambda b: b['date'])
    return bars


# --- Report ---

def render_comparison_table(reports: list[TimingBacktestReport]) -> str:
    lines = []
    lines.append("")
    lines.append("## 510300 单ETF择时因子回测对比")
    lines.append("")
    lines.append("| 因子 | 总收益 | 年化收益 | 最大回撤 | 夏普 | 卡玛 | 胜率 | 交易 | 持仓% |")
    lines.append("|------|--------|----------|----------|------|------|------|------|-------|")
    
    total_days = max(len(r.equity_curve) for r in reports) if reports else 1
    
    for r in reports:
        long_pct = r.long_days / total_days * 100 if total_days > 0 else 0
        lines.append(
            f"| {r.factor_name} | {r.total_return:+.2%} | {r.annual_return:+.2%} | "
            f"{r.max_drawdown:.2%} | {r.sharpe_ratio:.2f} | {r.calmar_ratio:.2f} | "
            f"{r.win_rate:.1%} | {r.trade_count} | {long_pct:.0f}% |"
        )
    
    return "\n".join(lines)


def render_full_report(reports: list[TimingBacktestReport], symbol: str, date_range: str) -> str:
    lines = []
    lines.append(f"# {symbol} 单ETF择时因子回测报告")
    lines.append(f"")
    lines.append(f"回测区间: {date_range}")
    lines.append(f"标的: {symbol} (沪深300ETF)")
    lines.append(f"初始资金: ¥100,000 | 手续费: 万三 | 滑点: 0.1%")
    lines.append(f"")
    
    lines.append(render_comparison_table(reports))
    
    # 排名
    sorted_by_sharpe = sorted(reports, key=lambda r: r.sharpe_ratio, reverse=True)
    sorted_by_return = sorted(reports, key=lambda r: r.annual_return, reverse=True)
    sorted_by_dd = sorted(reports, key=lambda r: r.max_drawdown, reverse=True)
    
    lines.append("")
    lines.append("## 排名")
    lines.append(f"- 夏普最高: {sorted_by_sharpe[0].factor_name} ({sorted_by_sharpe[0].sharpe_ratio:.2f})")
    lines.append(f"- 收益最高: {sorted_by_return[0].factor_name} ({sorted_by_return[0].annual_return:+.2%})")
    lines.append(f"- 回撤最小: {sorted_by_dd[0].factor_name} ({sorted_by_dd[0].max_drawdown:.2%})")
    
    # 因子解读
    lines.append("")
    lines.append("## 因子解读")
    for r in reports:
        lines.append(f"### {r.factor_name}")
        cat = FACTOR_REGISTRY.get(r.factor_name, {})
        lines.append(f"- 类别: {cat.get('category', 'N/A')}")
        lines.append(f"- 描述: {cat.get('description', 'N/A')}")
        lines.append(f"- 持仓占比: {r.long_days/max(len(r.equity_curve),1)*100:.0f}%")
        
        # 提取因子决策原因分布
        reason_counts = {}
        for s in r.signals:
            reason = s['reason']
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        top_reasons = sorted(reason_counts.items(), key=lambda x: -x[1])[:5]
        lines.append(f"- 信号分布: {', '.join(f'{k}({v})' for k,v in top_reasons)}")
    
    return "\n".join(lines)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="510300单ETF择时因子回测")
    parser.add_argument("--history", required=True, help="OHLCV CSV路径")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--factors", default="CHOP-FILTER,ADX-TREND,RSI-MREV,VOL-BREAK,VOL-CLIMAX",
                        help="逗号分隔的因子名")
    parser.add_argument("--output-md", default="", help="Markdown报告路径")
    parser.add_argument("--output-json", default="", help="JSON报告路径")
    args = parser.parse_args()
    
    print(f"加载数据: {args.history}")
    bars = load_ohlcv_csv(args.history)
    print(f"共 {len(bars)} 根K线")
    
    date_range = f"{bars[0]['date']} ~ {bars[-1]['date']}"
    print(f"日期范围: {date_range}")
    
    config = TimingBacktestConfig(initial_capital=args.initial_capital)
    
    factor_names = [f.strip() for f in args.factors.split(",")]
    
    reports = []
    for name in factor_names:
        if name not in FACTOR_REGISTRY:
            print(f"未知因子: {name}, 跳过")
            continue
        
        factor_info = FACTOR_REGISTRY[name]
        print(f"\n回测: {name} ...")
        
        report = run_timing_backtest(bars, factor_info['fn'], name, config)
        reports.append(report)
        
        long_pct = report.long_days / max(len(report.equity_curve), 1) * 100
        print(f"  {name}: 总={report.total_return:+.2%} 年化={report.annual_return:+.2%} "
              f"回撤={report.max_drawdown:.2%} 夏普={report.sharpe_ratio:.2f} "
              f"卡玛={report.calmar_ratio:.2f} 胜率={report.win_rate:.1%} "
              f"交易={report.trade_count} 持仓={long_pct:.0f}%")
    
    if not reports:
        print("没有有效的回测结果", file=sys.stderr)
        sys.exit(1)
    
    # 输出报告
    md = render_full_report(reports, "510300", date_range)
    print(md)
    
    if args.output_md:
        out = args.output_md
        if not Path(out).is_absolute():
            out = str(Path(__file__).resolve().parents[1] / out)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\nMarkdown报告: {out}")
    
    if args.output_json:
        jp = args.output_json
        if not Path(jp).is_absolute():
            jp = str(Path(__file__).resolve().parents[1] / jp)
        Path(jp).parent.mkdir(parents=True, exist_ok=True)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump([r.summary_dict() for r in reports], f, ensure_ascii=False, indent=2)
        print(f"JSON报告: {jp}")


if __name__ == "__main__":
    main()
