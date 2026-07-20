#!/usr/bin/env python3
"""多因子 ETF 轮动回测对比脚本。

同时测试多种因子在同一天数据上的选股表现，输出对比报告。
用法:
  python scripts/backtest_etf_multi_factor.py --history data/history/multi_etf_rotation.csv

因子:
  BASELINE - 原始动量因子 (MOM-ROT-001)
  VW-MOM   - 成交量加权动量
  SHARPE   - 夏普调整动量
  MA-STATE - 均线状态自适应
"""

import argparse
import csv
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.etf_momentum_rotation import (
    MomentumRotationConfig,
    evaluate_snapshot as evaluate_baseline_snapshot,
)
from research.etf_multi_factor import (
    VWMomConfig,
    SharpeMomConfig,
    MAStateConfig,
    RetSkewConfig,
    VolSurgeConfig,
    calc_vw_momentum,
    calc_sharpe_momentum,
    calc_ma_state,
    calc_ret_skew,
    calc_vol_surge,
    evaluate_multi_factor_snapshot,
    MultiFactorResult,
)


# --- 账户配置 ---
@dataclass
class AccountConfig:
    initial_capital: float = 100000
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    slippage_rate: float = 0.001

# --- Backtest Engine ---

@dataclass
class BacktestReport:
    factor_name: str
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    trade_count: int
    avg_holdings: float
    cash_days: int
    equity_curve: list[dict]
    trades: list[dict]
    
    def summary_dict(self) -> dict:
        return {
            "factor": self.factor_name,
            "total_return": round(self.total_return, 4),
            "annual_return": round(self.annual_return, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "win_rate": round(self.win_rate, 4),
            "trade_count": self.trade_count,
            "avg_holdings": round(self.avg_holdings, 3),
            "cash_days": self.cash_days,
        }


def run_backtest_for_factor(
    history: list[dict],
    factor_config,
    factor_name: str,
    calc_fn,
    account: AccountConfig,
    rebalance_step: int = 5,
    is_baseline: bool = False,
) -> BacktestReport:
    """用指定因子运行回测。"""
    
    symbols_list = list(history[0]["symbols"].keys()) if history else []
    
    cash = account.initial_capital
    positions = {}        # symbol -> {shares, avg_price}
    equity_curve = []
    trades_log = []
    last_snapshot_idx = -1
    
    trade_dates_by_signal = []  # 记录每次调仓日期
    
    for idx, snapshot in enumerate(history):
        date = snapshot["date"]
        
        # 评估
        if idx % rebalance_step != 0:
            # 非调仓日: 只记录净值
            if idx > 0:
                equity_curve.append(_calc_equity_point(
                    date, cash, positions, snapshot, equity_curve, account
                ))
            continue
        
        if is_baseline:
            result = evaluate_baseline_snapshot(snapshot, factor_config)
            selected = result.get("selected", [])
        else:
            result = evaluate_multi_factor_snapshot(
                snapshot, factor_config, factor_name, calc_fn
            )
            selected = result.selected
        
        # 卖出不在选中列表的持仓
        for symbol, pos in list(positions.items()):
            if symbol not in selected and pos["shares"] > 0:
                close_price = _get_price(snapshot, symbol)
                if close_price <= 0:
                    continue
                shares = int(pos["shares"] // 100) * 100
                if shares <= 0:
                    continue
                proceeds = shares * close_price
                commission = max(proceeds * account.commission_rate, account.min_commission)
                # 滑点
                proceeds_after = proceeds * (1 - account.slippage_rate) - commission
                
                cost_basis = pos["shares"] * pos["avg_price"]
                profit = proceeds_after - cost_basis
                
                cash += proceeds_after
                trades_log.append({
                    "date": date,
                    "action": "SELL",
                    "symbol": symbol,
                    "price": close_price,
                    "shares": shares,
                    "amount": proceeds,
                    "commission": commission,
                    "profit": profit,
                })
                del positions[symbol]
        
        # 买入选中的 ETF（等权配置）
        if selected:
            target_count = len(selected)
            # 先计算现有持仓市值
            existing_symbols = set(positions.keys())
            to_buy = [s for s in selected if s not in existing_symbols]
            
            if to_buy:
                # 计算总资产
                positions_value = sum(
                    pos["shares"] * _get_price(snapshot, sym)
                    for sym, pos in positions.items()
                )
                total_value = cash + positions_value
                per_position = total_value / target_count
                
                for symbol in to_buy:
                    close_price = _get_price(snapshot, symbol)
                    if close_price <= 0:
                        continue
                    
                    budget = per_position
                    max_shares = int(budget / (close_price * (1 + account.slippage_rate)) / 100) * 100
                    
                    if max_shares <= 0:
                        continue
                    
                    cost = max_shares * close_price * (1 + account.slippage_rate)
                    commission = max(cost * account.commission_rate, account.min_commission)
                    total_cost = cost + commission
                    
                    if total_cost > cash:
                        max_shares = int((cash - commission) / (close_price * (1 + account.slippage_rate)) / 100) * 100
                        if max_shares <= 0:
                            continue
                        cost = max_shares * close_price * (1 + account.slippage_rate)
                        commission = max(cost * account.commission_rate, account.min_commission)
                        total_cost = cost + commission
                    
                    cash -= total_cost
                    positions[symbol] = {
                        "shares": max_shares,
                        "avg_price": close_price,
                    }
                    
                    trades_log.append({
                        "date": date,
                        "action": "BUY",
                        "symbol": symbol,
                        "price": close_price,
                        "shares": max_shares,
                        "amount": cost,
                        "commission": commission,
                        "profit": 0,
                    })
            
            trade_dates_by_signal.append(date)
        
        # 记录净值
        equity_curve.append(_calc_equity_point(
            date, cash, positions, snapshot, equity_curve, account
        ))
    
    # 计算绩效指标
    return _compute_performance(factor_name, equity_curve, trades_log, account)


def _get_price(snapshot: dict, symbol: str) -> float:
    bar = snapshot["symbols"].get(symbol, {})
    if not bar:
        return 0.0
    close = bar.get("close", 0)
    prices_str = bar.get("prices", "")
    if close <= 0 and prices_str:
        parts = prices_str.split("|")
        if parts:
            try:
                close = float(parts[-1])
            except ValueError:
                close = 0.0
    return close


def _calc_equity_point(
    date: str,
    cash: float,
    positions: dict,
    snapshot: dict,
    prev_curve: list,
    account: AccountConfig,
) -> dict:
    positions_value = 0
    for sym, pos in positions.items():
        price = _get_price(snapshot, sym)
        positions_value += pos["shares"] * price
    
    total_value = cash + positions_value
    
    prev_value = account.initial_capital
    if prev_curve:
        prev_value = prev_curve[-1]["total_value"]
    
    period_return = (total_value - prev_value) / prev_value if prev_value > 0 else 0
    
    peak = max(p["total_value"] for p in prev_curve) if prev_curve else total_value
    peak = max(peak, total_value)
    drawdown = (total_value - peak) / peak if peak > 0 else 0
    
    return {
        "date": date,
        "cash": cash,
        "positions_value": positions_value,
        "total_value": total_value,
        "period_return": period_return,
        "drawdown": drawdown,
    }


def _compute_performance(
    factor_name: str,
    equity_curve: list[dict],
    trades: list[dict],
    account: AccountConfig,
) -> BacktestReport:
    if not equity_curve:
        return BacktestReport(
            factor_name=factor_name,
            total_return=0, annual_return=0, max_drawdown=0,
            sharpe_ratio=0, win_rate=0, trade_count=0,
            avg_holdings=0, cash_days=0,
            equity_curve=[], trades=[],
        )
    
    # 总收益
    final_value = equity_curve[-1]["total_value"]
    total_return = (final_value - account.initial_capital) / account.initial_capital
    
    # 年化收益
    days = len(equity_curve)
    years = days / 252
    annual_return = (final_value / account.initial_capital) ** (1 / max(years, 0.01)) - 1
    
    # 最大回撤
    max_dd = min(p["drawdown"] for p in equity_curve)
    
    # 日收益率
    daily_returns = [p["period_return"] for p in equity_curve if p["period_return"] != 0]
    
    # 夏普比率
    if daily_returns and len(daily_returns) > 1:
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_ret = math.sqrt(variance)
        if std_ret > 0:
            sharpe = (mean_ret / std_ret) * math.sqrt(252)
        else:
            sharpe = 0
    else:
        sharpe = 0
    
    # 胜率（按卖出交易的盈亏）
    sell_trades = [t for t in trades if t["action"] == "SELL"]
    wins = [t for t in sell_trades if t["profit"] > 0]
    win_rate = len(wins) / len(sell_trades) if sell_trades else 0
    
    # 交易次数
    trade_count = len(trades)
    
    # 平均持仓数
    holding_counts = []
    current_positions = {}
    # 简化: 用 trades 推断
    for t in trades:
        if t["action"] == "BUY":
            current_positions[t["symbol"]] = True
        elif t["action"] == "SELL":
            current_positions.pop(t["symbol"], None)
    avg_holdings = 0  # 简化
    
    # 空仓天数
    positions_value_list = [p.get("positions_value", 0) for p in equity_curve]
    cash_days = sum(1 for v in positions_value_list if v < 100)
    
    return BacktestReport(
        factor_name=factor_name,
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        win_rate=win_rate,
        trade_count=trade_count,
        avg_holdings=avg_holdings,
        cash_days=cash_days,
        equity_curve=equity_curve,
        trades=trades,
    )


# --- 持仓持有天数统计 ---

def _count_holding_days(equity_curve, trades):
    """统计平均持仓天数"""
    return 0


# --- CSV 加载 ---

def load_snapshots_from_csv(path: str) -> list[dict]:
    """从 rotation CSV 加载快照。复用现有 loader。"""
    from research.etf_momentum_rotation import load_rotation_csv
    return load_rotation_csv(path)


# --- 报告输出 ---

def render_comparison_table(reports: list[BacktestReport]) -> str:
    """生成对比表格。"""
    lines = []
    lines.append("")
    lines.append("## 多因子回测对比报告")
    lines.append("")
    lines.append("| 因子 | 总收益 | 年化收益 | 最大回撤 | 夏普比率 | 胜率 | 交易次数 |")
    lines.append("|------|--------|----------|----------|----------|------|----------|")
    
    for r in reports:
        # 排名标记
        total_ret_str = f"{r.total_return:+.2%}"
        ann_ret_str = f"{r.annual_return:+.2%}"
        dd_str = f"{r.max_drawdown:.2%}"
        sharpe_str = f"{r.sharpe_ratio:.2f}"
        wr_str = f"{r.win_rate:.1%}"
        
        lines.append(
            f"| {r.factor_name} | {total_ret_str} | {ann_ret_str} | "
            f"{dd_str} | {sharpe_str} | {wr_str} | {r.trade_count} |"
        )
    
    return "\n".join(lines)


def render_markdown_report(reports: list[BacktestReport], etf_pool: list[str], date_range: str) -> str:
    """生成完整的 Markdown 报告。"""
    lines = []
    lines.append(f"# ETF 多因子回测报告")
    lines.append(f"")
    lines.append(f"**回测区间**: {date_range}")
    lines.append(f"**ETF 池**: {', '.join(etf_pool)}")
    lines.append(f"**初始资金**: ¥100,000")
    lines.append(f"**手续费**: 0.03% (最低¥5)")
    lines.append(f"**滑点**: 0.1%")
    lines.append(f"")
    
    lines.append(render_comparison_table(reports))
    
    # 排名总结
    sorted_by_sharpe = sorted(reports, key=lambda r: r.sharpe_ratio, reverse=True)
    lines.append("")
    lines.append("## 排名（按夏普比率）")
    for i, r in enumerate(sorted_by_sharpe, 1):
        lines.append(f"{i}. **{r.factor_name}** — 年化 {r.annual_return:+.2%}, 回撤 {r.max_drawdown:.2%}, 夏普 {r.sharpe_ratio:.2f}")
    
    # 推荐
    best = sorted_by_sharpe[0]
    best_return = sorted(reports, key=lambda r: r.annual_return, reverse=True)[0]
    best_dd = sorted(reports, key=lambda r: r.max_drawdown, reverse=True)[0]
    
    lines.append("")
    lines.append("## 综合评估")
    lines.append(f"- **最优风险调整**: {best.factor_name} (夏普 {best.sharpe_ratio:.2f})")
    lines.append(f"- **最高收益**: {best_return.factor_name} (年化 {best_return.annual_return:+.2%})")
    lines.append(f"- **最小回撤**: {best_dd.factor_name} (最大回撤 {best_dd.max_drawdown:.2%})")
    
    # 净值曲线数据
    lines.append("")
    lines.append("## 净值曲线")
    lines.append("")
    lines.append("| 日期 | " + " | ".join(r.factor_name for r in reports) + " |")
    lines.append("|------|" + "|".join("------" for _ in reports) + "|")
    
    # 找到所有日期（取任意一个因子的全部日期）
    all_dates = sorted(set(p["date"] for r in reports for p in r.equity_curve))
    
    for d in all_dates:
        values = []
        for r in reports:
            point = next((p for p in r.equity_curve if p["date"] == d), None)
            if point:
                values.append(f"{point['total_value']:.2f}")
            else:
                values.append("-")
        lines.append(f"| {d} | " + " | ".join(values) + " |")
    
    return "\n".join(lines)


def save_reports_json(reports: list[BacktestReport], output_path: str):
    """保存报告为 JSON。"""
    data = []
    for r in reports:
        data.append(r.summary_dict())
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON 报告已保存: {output_path}")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="多因子 ETF 轮动回测对比")
    parser.add_argument("--history", required=True, help="rotation CSV 路径")
    parser.add_argument("--etf-pool", default="", help="逗号分隔 ETF 池（默认使用 CSV 中出现的全部）")
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--output-json", default="", help="JSON 报告输出路径")
    parser.add_argument("--output-md", default="", help="Markdown 报告输出路径")
    parser.add_argument(
        "--factors",
        default="BASELINE,VW-MOM,SHARPE,MA-STATE",
        help="逗号分隔的因子列表"
    )
    args = parser.parse_args()
    
    # 加载数据
    print(f"加载历史数据: {args.history}")
    snapshots = load_snapshots_from_csv(args.history)
    print(f"加载 {len(snapshots)} 个交易日快照")
    
    if not snapshots:
        print("无数据", file=sys.stderr)
        sys.exit(1)
    
    # ETF 池
    if args.etf_pool:
        etf_pool = [s.strip() for s in args.etf_pool.split(",") if s.strip()]
    else:
        etf_pool = list(snapshots[0]["symbols"].keys())
    
    date_range = f"{snapshots[0]['date']} ~ {snapshots[-1]['date']}"
    print(f"ETF 池: {etf_pool}")
    print(f"日期范围: {date_range}")
    
    # 账户配置
    account = AccountConfig(initial_capital=args.initial_capital)
    
    # 因子配置
    factor_specs = []
    requested = set(f.strip().upper() for f in args.factors.split(","))
    
    if "BASELINE" in requested:
        factor_specs.append((
            "BASELINE",
            MomentumRotationConfig(
                momentum_window=60,
                confirm_window=20,
                volatility_window=20,
                min_history_days=120,
                max_holdings=2,
            ),
            None,
            True,  # is_baseline
        ))
    
    if "VW-MOM" in requested:
        factor_specs.append((
            "VW-MOM",
            VWMomConfig(momentum_window=60, min_history_days=120, max_holdings=2),
            calc_vw_momentum,
            False,
        ))
    
    if "SHARPE" in requested:
        factor_specs.append((
            "SHARPE",
            SharpeMomConfig(momentum_window=60, volatility_window=20, min_history_days=120, max_holdings=2),
            calc_sharpe_momentum,
            False,
        ))
    
    if "MA-STATE" in requested:
        factor_specs.append((
            "MA-STATE",
            MAStateConfig(short_ma=20, long_ma=60, momentum_window=60, min_history_days=120, max_holdings=2),
            calc_ma_state,
            False,
        ))
    
    if "RET-SKEW" in requested:
        factor_specs.append((
            "RET-SKEW",
            RetSkewConfig(skew_window=60, min_history_days=120, max_holdings=2),
            calc_ret_skew,
            False,
        ))
    
    if "VOL-SURGE" in requested:
        factor_specs.append((
            "VOL-SURGE",
            VolSurgeConfig(vol_lookback=20, min_history_days=120, max_holdings=2),
            calc_vol_surge,
            False,
        ))
    
    # 运行回测
    reports = []
    for name, config, calc_fn, is_baseline in factor_specs:
        print(f"\n运行回测: {name} ...")
        report = run_backtest_for_factor(
            snapshots, config, name, calc_fn, account, is_baseline=is_baseline
        )
        reports.append(report)
        print(f"  {name}: 总收益={report.total_return:+.2%} 年化={report.annual_return:+.2%} "
              f"回撤={report.max_drawdown:.2%} 夏普={report.sharpe_ratio:.2f} "
              f"交易={report.trade_count}次")
    
    # 输出报告
    md = render_markdown_report(reports, etf_pool, date_range)
    print(md)
    
    if args.output_md:
        output_path = args.output_md
        if not Path(output_path).is_absolute():
            output_path = str(Path(__file__).resolve().parents[1] / output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\nMarkdown 报告已保存: {output_path}")
    
    if args.output_json:
        json_path = args.output_json
        if not Path(json_path).is_absolute():
            json_path = str(Path(__file__).resolve().parents[1] / json_path)
        save_reports_json(reports, json_path)


if __name__ == "__main__":
    main()
