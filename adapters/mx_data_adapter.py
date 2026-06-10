import json
import subprocess

from .base_adapter import BaseAdapter


class MXDataAdapter(BaseAdapter):

    def __init__(self, config):
        super().__init__(config)

    def connect(self):
        if self.mode == 'mock':
            super().connect()
            return

        if not self._history_command_configured():
            self.connected = False
            self.last_error = 'real history provider not configured'
            return

        self.connected = True
        self.last_error = ''

    def health_check(self) -> dict:
        status = super().health_check()
        status.update({
            'history_provider': (
                'command' if self._history_command_configured() else None
            ),
            'history_available': (
                self.connected and self._history_command_configured()
            ),
        })
        return status

    def get_etf_realtime(self, symbol: str) -> dict:
        self._ensure_mock_operation('realtime')
        return {
            'symbol': symbol,
            'price': 0.0,
            'open': 0.0,
            'high': 0.0,
            'low': 0.0,
            'pre_close': 0.0,
            'volume': 0,
            'amount': 0.0,
            'timestamp': ''
        }

    def get_etf_history(self, symbol: str, start_date: str, end_date: str) -> list:
        from data.contracts import DataFetchError, ServiceUnavailableError

        if self.mode == 'mock':
            self._ensure_available()
            return []

        self._ensure_real_history_available()
        command = self._build_history_command(symbol, start_date, end_date)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=self.config.get('timeout', 10),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ServiceUnavailableError(
                f"MXDataAdapter history provider failed: {exc}",
                error_code='REAL_HISTORY_PROVIDER_FAILED',
                source='MXDataAdapter',
            ) from exc

        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip()
            raise ServiceUnavailableError(
                f"MXDataAdapter history provider exited with "
                f"{completed.returncode}: {error or '-'}",
                error_code='REAL_HISTORY_PROVIDER_FAILED',
                source='MXDataAdapter',
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise DataFetchError(
                'MXDataAdapter history provider output is not valid JSON',
                error_code='INVALID_PROVIDER_RESPONSE',
                source='MXDataAdapter',
            ) from exc

        if isinstance(payload, dict):
            payload = payload.get('history', payload.get('data'))
        if not isinstance(payload, list):
            raise DataFetchError(
                'MXDataAdapter history provider JSON must be a list or contain history/data list',
                error_code='INVALID_PROVIDER_RESPONSE',
                source='MXDataAdapter',
            )
        return payload

    def get_etf_nav(self, symbol: str) -> dict:
        self._ensure_mock_operation('nav')
        return {
            'symbol': symbol,
            'nav': 0.0,
            'price': 0.0,
            'premium': 0.0,
            'timestamp': ''
        }

    def get_etf_list(self, etf_type: str = None) -> list:
        self._ensure_mock_operation('etf_list')
        return []

    def _history_command_configured(self) -> bool:
        command = self.config.get('history_command')
        return (
            isinstance(command, list)
            and bool(command)
            and all(isinstance(part, str) and part for part in command)
        )

    def _ensure_mock_operation(self, operation: str) -> None:
        from data.contracts import ServiceUnavailableError

        if self.mode == 'real':
            raise ServiceUnavailableError(
                f"MXDataAdapter real {operation} operation is not implemented",
                error_code='REAL_OPERATION_NOT_IMPLEMENTED',
                source='MXDataAdapter',
            )
        self._ensure_available()

    def _ensure_real_history_available(self) -> None:
        from data.contracts import ServiceUnavailableError

        if not self._history_command_configured():
            raise ServiceUnavailableError(
                'MXDataAdapter real history provider is not configured',
                error_code='REAL_HISTORY_PROVIDER_NOT_CONFIGURED',
                source='MXDataAdapter',
            )
        if not self.connected:
            raise ServiceUnavailableError(
                'MXDataAdapter real history provider is not connected',
                error_code='ADAPTER_NOT_CONNECTED',
                source='MXDataAdapter',
            )

    def _build_history_command(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[str]:
        values = {
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
        }
        try:
            return [
                part.format(**values)
                for part in self.config['history_command']
            ]
        except KeyError as exc:
            raise ValueError(
                f"history_command contains unknown placeholder: {exc.args[0]}"
            ) from exc
