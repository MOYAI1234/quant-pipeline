from datetime import datetime


class ReportGenerator:

    def __init__(self, config):
        self.config = config

    def generate_daily_report(
        self,
        portfolio: dict,
        strategy_summary: dict,
        data_health: dict | None = None,
        alerts: list | None = None,
        cache_policy: dict | None = None,
    ) -> str:
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
        self._append_data_health(report, data_health, cache_policy)
        self._append_alerts(report, alerts)
        return "\n".join(report)

    def generate_weekly_report(
        self,
        portfolio: dict,
        strategy_summary: dict,
        data_health: dict | None = None,
        alerts: list | None = None,
        cache_policy: dict | None = None,
    ) -> str:
        report = []
        report.append(f"# 周度报告 - {datetime.now().strftime('%Y-%m-%d')}")
        report.append("")
        report.append("## 账户状态")
        report.append(f"- 总价值: {portfolio.get('total_value', 0):.2f}")
        report.append(f"- 盈亏: {portfolio.get('pnl', 0):.2f} ({portfolio.get('pnl_percent', 0):.2f}%)")
        self._append_data_health(report, data_health, cache_policy)
        self._append_alerts(report, alerts)
        return "\n".join(report)

    def _append_data_health(
        self,
        report: list,
        data_health: dict | None,
        cache_policy: dict | None = None,
    ):
        if data_health is None:
            return

        available = bool(data_health) and all(
            status.get('available', False)
            for status in data_health.values()
        )
        mock = bool(data_health) and all(
            status.get('mock', False)
            for status in data_health.values()
        )
        overall = 'OK' if available else 'FAIL'
        mode = 'mock' if mock else 'mixed/real'

        report.append("")
        report.append("## 数据源状态")
        report.append(f"- 总体: {overall} ({mode})")
        if cache_policy:
            history_ttl = cache_policy.get('history_ttl_seconds')
            report.append(f"- 缓存: history_ttl_seconds={history_ttl}")
        for name, status in data_health.items():
            availability = '可用' if status.get('available') else '不可用'
            error = status.get('error') or '-'
            report.append(
                f"- {name}: {availability}, mode={status.get('mode')}, "
                f"service={status.get('service')}, error={error}"
            )

    def _append_alerts(self, report: list, alerts: list | None):
        if alerts is None:
            return

        report.append("")
        report.append("## 告警事件")
        if not alerts:
            report.append("- 无")
            return

        for alert in alerts:
            level = alert.get('level', 'warning')
            category = alert.get('category', 'system')
            message = alert.get('message', '')
            timestamp = alert.get('timestamp') or '-'
            report.append(
                f"- [{level}] {category}: {message} ({timestamp})"
            )
