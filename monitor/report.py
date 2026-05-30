from datetime import datetime


class ReportGenerator:

    def __init__(self, config):
        self.config = config

    def generate_daily_report(self, portfolio: dict, strategy_summary: dict) -> str:
        report = []
        report.append(f"# 每日报告 - {datetime.now().strftime('%Y-%m-%d')}")
        report.append("")
        report.append("## 账户状态")
        report.append(f"- 资金: {portfolio.get('capital', 0):.2f}")
        report.append(f"- 持仓数: {portfolio.get('position_count', 0)}")
        report.append(f"- 总价值: {portfolio.get('total_value', 0):.2f}")
        report.append(f"- 盈亏: {portfolio.get('pnl', 0):.2f} ({portfolio.get('pnl_percent', 0):.2f}%)")
        report.append("")
        report.append("## 策略表现")
        for name, perf in strategy_summary.items():
            report.append(f"### {name}")
            report.append(f"- 交易次数: {perf.get('total_trades', 0)}")
            report.append(f"- 胜率: {perf.get('win_rate', 0):.2%}")
            report.append(f"- 总收益: {perf.get('total_profit', 0):.2f}")
        return "\n".join(report)

    def generate_weekly_report(self, portfolio: dict, strategy_summary: dict) -> str:
        report = []
        report.append(f"# 周度报告 - {datetime.now().strftime('%Y-%m-%d')}")
        report.append("")
        report.append("## 账户状态")
        report.append(f"- 总价值: {portfolio.get('total_value', 0):.2f}")
        report.append(f"- 盈亏: {portfolio.get('pnl', 0):.2f} ({portfolio.get('pnl_percent', 0):.2f}%)")
        return "\n".join(report)
