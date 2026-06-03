from datetime import datetime
from .alert import AlertManager


class SystemMonitor:

    def __init__(self, config):
        self.config = config
        self.alert_manager = AlertManager(config)
        self.metrics = {}

    def update_metrics(self, portfolio: dict, strategy_summary: dict):
        self.metrics = {
            'timestamp': datetime.now(),
            'capital': portfolio.get('capital', 0),
            'position': portfolio.get('position_count', 0),
            'total_value': portfolio.get('total_value', 0),
            'pnl': portfolio.get('pnl', 0),
            'pnl_percent': portfolio.get('pnl_percent', 0),
            'strategy_summary': strategy_summary,
        }
        self.check_alerts()

    def check_alerts(self):
        alerts = []
        alert_threshold = self.config.get('alert_threshold', -10)

        if self.metrics.get('pnl_percent', 0) < alert_threshold:
            alerts.append({
                'message': f"亏损告警: {self.metrics['pnl_percent']:.2f}%",
                'level': 'warning',
                'category': 'risk.pnl',
                'payload': {
                    'pnl_percent': self.metrics['pnl_percent'],
                    'threshold': alert_threshold,
                },
            })

        max_position = self.config.get('max_position', 5)
        if self.metrics.get('position', 0) >= max_position:
            alerts.append({
                'message': f"持仓告警: {self.metrics['position']}格",
                'level': 'warning',
                'category': 'risk.position',
                'payload': {
                    'position': self.metrics['position'],
                    'max_position': max_position,
                },
            })

        for alert in alerts:
            self.alert_manager.send_alert(**alert)

    def get_metrics(self) -> dict:
        return self.metrics

    def get_alert_history(self, limit: int = 10) -> list:
        return self.alert_manager.get_alert_history(limit)

    def print_status(self):
        print(f"时间: {self.metrics.get('timestamp', '')}")
        print(f"资金: {self.metrics.get('capital', 0):.2f}")
        print(f"持仓: {self.metrics.get('position', 0)}")
        print(f"总价值: {self.metrics.get('total_value', 0):.2f}")
        print(f"盈亏: {self.metrics.get('pnl', 0):.2f} ({self.metrics.get('pnl_percent', 0):.2f}%)")
        print("-" * 50)
