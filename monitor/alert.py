import logging
import json
from datetime import datetime
from pathlib import Path


class AlertManager:

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger('quant_pipeline.alert')
        self.alert_history = []
        self.alert_file_path = config.get('alert_file_path')

    def send_alert(
        self,
        message: str,
        level: str = 'warning',
        category: str = 'system',
        payload: dict | None = None,
    ) -> dict:
        alert = {
            'message': message,
            'level': level,
            'category': category,
            'payload': dict(payload or {}),
            'timestamp': datetime.now().isoformat(),
        }
        self.alert_history.append(alert)
        self._log_alert(alert)
        self._write_alert(alert)
        return alert

    def get_alert_history(self, limit: int = 10) -> list:
        return self.alert_history[-limit:]

    def _log_alert(self, alert: dict):
        log_message = f"[ALERT][{alert['category']}] {alert['message']}"
        log_method = getattr(
            self.logger,
            str(alert['level']).lower(),
            self.logger.warning,
        )
        if not callable(log_method):
            log_method = self.logger.warning
        log_method(log_message)

    def _write_alert(self, alert: dict):
        if not self.alert_file_path:
            return

        path = Path(self.alert_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as file:
            file.write(json.dumps(alert, ensure_ascii=False) + "\n")
