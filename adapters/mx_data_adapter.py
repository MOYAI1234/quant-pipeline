import json
import os
from pathlib import Path
import shutil
import subprocess
from string import Formatter

from .base_adapter import BaseAdapter


class MXDataAdapter(BaseAdapter):
    ALLOWED_HISTORY_PLACEHOLDERS = frozenset({
        'symbol',
        'start_date',
        'end_date',
    })

    def __init__(self, config):
        super().__init__(config)

    def connect(self):
        if self.mode == 'mock':
            super().connect()
            return

        command_error = self._history_command_error()
        if command_error:
            self.connected = False
            self.last_error = command_error
            return

        self.connected = True
        self.last_error = ''

    def health_check(self) -> dict:
        status = super().health_check()
        command_error = self._history_command_error()
        if self.mode == 'real':
            status['available'] = False
            if command_error:
                status['connected'] = False
                status['error'] = command_error
        status.update({
            'history_provider': None if command_error else 'command',
            'history_available': (
                self.mode == 'real'
                and self.connected
                and not command_error
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
        """Return historical bars.

        Real providers must emit bounded JSON to stdout; stdout/stderr are
        captured in memory rather than streamed.
        """
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
        return self._history_command_error() == ''

    def _history_command_error(self) -> str:
        command = self.config.get('history_command')
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            return 'real history provider not configured'

        for part in command:
            try:
                for _, field_name, format_spec, conversion in Formatter().parse(part):
                    if field_name is None:
                        continue
                    if field_name not in self.ALLOWED_HISTORY_PLACEHOLDERS:
                        return f'history_command contains unknown placeholder: {field_name}'
                    if format_spec or conversion:
                        return 'history_command placeholders do not support format specifiers'
            except ValueError as exc:
                return f'history_command template invalid: {exc}'

        try:
            sample_command = self._format_history_command({
                'symbol': '510300',
                'start_date': '2026-01-01',
                'end_date': '2026-01-02',
            })
        except (KeyError, ValueError) as exc:
            return f'history_command template invalid: {exc}'

        executable = sample_command[0]
        if self._is_path_like_command(executable):
            executable_path = Path(executable)
            if not executable_path.exists():
                return f'history_command executable not found: {executable}'
            if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
                return f'history_command executable is not executable: {executable}'
        elif shutil.which(executable) is None:
            return f'history_command executable not found: {executable}'
        return ''

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

        command_error = self._history_command_error()
        if command_error:
            raise ServiceUnavailableError(
                f'MXDataAdapter real history provider is unavailable: {command_error}',
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
        from data.contracts import ServiceUnavailableError

        try:
            return self._format_history_command({
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date,
            })
        except (KeyError, ValueError) as exc:
            raise ServiceUnavailableError(
                f'MXDataAdapter history command is invalid: {exc}',
                error_code='REAL_HISTORY_PROVIDER_NOT_CONFIGURED',
                source='MXDataAdapter',
            ) from exc

    def _format_history_command(self, values: dict) -> list[str]:
        return [
            part.format(**values)
            for part in self.config['history_command']
        ]

    def _is_path_like_command(self, executable: str) -> bool:
        return (
            Path(executable).is_absolute()
            or '/' in executable
            or '\\' in executable
        )
