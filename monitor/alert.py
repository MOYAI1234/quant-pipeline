import logging
from datetime import datetime


class AlertManager:

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger('quant_pipeline.alert')
        self.alert_history = []

    def send_alert(self, message: str, level: str = 'warning'):
        alert = {
            'message': message,
            'level': level,
            'timestamp': datetime.now()
        }
        self.alert_history.append(alert)
        self.logger.warning(f"[ALERT] {message}")

    def get_alert_history(self, limit: int = 10) -> list:
        return self.alert_history[-limit:]
