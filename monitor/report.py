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
            history_hits = cache_policy.get('history_cache_hits', 0)
            history_misses = cache_policy.get('history_cache_misses', 0)
            last_hit = cache_policy.get('last_history_cache_hit')
            last_hit_text = '-' if last_hit is None else str(last_hit).lower()
            report.append(
                f"- 缓存: history_ttl_seconds={history_ttl}, "
                f"history_hits={history_hits}, "
                f"history_misses={history_misses}, "
                f"last_history_hit={last_hit_text}"
            )
        for name, status in data_health.items():
            availability = '可用' if status.get('available') else '不可用'
            error = status.get('error') or '-'
            report.append(
                f"- {name}: {availability}, mode={status.get('mode')}, "
                f"service={status.get('service')}, error={error}"
            )
            provider_summary = self._format_history_provider_summary(name, status)
            if provider_summary:
                report.append(provider_summary)

    def _format_history_provider_summary(
        self,
        name: str,
        status: dict,
    ) -> str | None:
        if not self._has_history_provider_status(status):
            return None
        availability = '可用' if status.get('history_available') else '不可用'
        provider = status.get('history_provider') or '-'
        ready = status.get('history_provider_ready_count', 0)
        count = status.get('history_provider_count', 0)
        last = status.get('last_history_provider') or '-'
        attempts = status.get('last_history_attempts', 0)
        failures = len(status.get('last_history_failures') or [])
        return (
            f"- {name} history: {availability}, provider={provider}, "
            f"ready={ready}/{count}, last={last}, attempts={attempts}, "
            f"failures={failures}"
        )

    def _has_history_provider_status(self, status: dict) -> bool:
        return any(
            key in status
            for key in (
                'history_provider',
                'history_provider_count',
                'history_available',
                'last_history_provider',
                'last_history_attempts',
                'last_history_failures',
            )
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
