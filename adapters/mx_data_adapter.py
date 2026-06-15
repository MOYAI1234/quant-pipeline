import json
import math
import os
from pathlib import Path
from numbers import Real
import shutil
import subprocess
from string import Formatter
import time

from .base_adapter import BaseAdapter


class MXDataAdapter(BaseAdapter):
    MAX_HISTORY_RETRY_ATTEMPTS = 10
    MAX_HISTORY_RETRY_DELAY_SECONDS = 60
    ALLOWED_HISTORY_PLACEHOLDERS = frozenset({
        'symbol',
        'start_date',
        'end_date',
    })

    def __init__(self, config):
        super().__init__(config)
        self.last_history_provider = None
        self.last_history_attempts = 0
        self.last_history_error = ''
        self.last_history_failures = []

    def connect(self):
        if self.mode == 'mock':
            super().connect()
            return

        command_error = self._history_command_error()
        if command_error:
            self.connected = False
            self.last_error = command_error
            return

        provider_statuses = self._history_provider_statuses()
        if not any(status['ready'] for status in provider_statuses):
            self.connected = False
            self.last_error = self._format_missing_provider_env(provider_statuses)
            return

        self.connected = True
        self.last_error = ''

    def health_check(self) -> dict:
        status = super().health_check()
        command_error = self._history_command_error()
        provider_statuses = (
            [] if command_error else self._history_provider_statuses()
        )
        if self.mode == 'real':
            status['available'] = False
            if command_error:
                status['connected'] = False
                status['error'] = command_error
        status.update({
            'history_provider': None if command_error else 'command',
            'history_provider_count': (
                0 if command_error else len(self._history_provider_configs())
            ),
            'history_provider_ready_count': (
                0 if command_error else sum(
                    provider_status['ready']
                    for provider_status in provider_statuses
                )
            ),
            'history_providers': provider_statuses,
            'history_available': (
                self.mode == 'real'
                and self.connected
                and not command_error
            ),
            'last_history_provider': self.last_history_provider,
            'last_history_attempts': self.last_history_attempts,
            'last_history_error': self.last_history_error,
            'last_history_failures': self.last_history_failures,
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
        self.last_history_provider = None
        self.last_history_attempts = 0
        self.last_history_error = ''
        self.last_history_failures = []
        failures = []
        retry_attempts = self.config.get('history_retry_attempts', 1)
        retry_delay = self.config.get('history_retry_delay_seconds', 0)

        provider_configs = self._history_provider_configs()
        for provider in provider_configs:
            missing_env = self._missing_provider_env(provider)
            if missing_env:
                self.last_history_attempts += 1
                exc = ServiceUnavailableError(
                    f"history provider {provider['name']} missing required "
                    f"environment variables: {', '.join(missing_env)}",
                    error_code='REAL_HISTORY_PROVIDER_ENV_MISSING',
                    source='MXDataAdapter',
                )
                failures.append((provider['name'], 1, exc))
                self._record_history_failure(provider['name'], 1, exc)
                continue
            for attempt in range(1, retry_attempts + 1):
                self.last_history_attempts += 1
                try:
                    payload = self._run_history_provider(
                        provider,
                        symbol,
                        start_date,
                        end_date,
                    )
                except ServiceUnavailableError as exc:
                    failures.append((provider['name'], attempt, exc))
                    self._record_history_failure(provider['name'], attempt, exc)
                    if attempt < retry_attempts and retry_delay > 0:
                        time.sleep(retry_delay)
                    continue
                except DataFetchError as exc:
                    failures.append((provider['name'], attempt, exc))
                    self._record_history_failure(provider['name'], attempt, exc)
                    break

                self.last_history_provider = provider['name']
                self.last_history_error = self._format_history_failures(failures)
                return payload

        details = self._format_history_failures(failures)
        self.last_history_error = details
        if len(failures) == 1 and len(provider_configs) == 1:
            raise failures[0][2]
        error_type = (
            DataFetchError
            if failures and all(
                isinstance(exc, DataFetchError)
                for _, _, exc in failures
            )
            else ServiceUnavailableError
        )
        error_code = (
            'INVALID_PROVIDER_RESPONSE'
            if error_type is DataFetchError
            else 'REAL_HISTORY_PROVIDERS_FAILED'
        )
        raise error_type(
            f'MXDataAdapter all history providers failed: {details or "-"}',
            error_code=error_code,
            source='MXDataAdapter',
        )

    def _record_history_failure(self, name: str, attempt: int, exc) -> None:
        self.last_history_failures.append({
            'provider': name,
            'attempt': attempt,
            'error_code': exc.error_code,
            'error': str(exc),
        })

    def _format_history_failures(self, failures: list) -> str:
        return '; '.join(
            f'{name} attempt {attempt}: {exc}'
            for name, attempt, exc in failures
        )

    def _run_history_provider(
        self,
        provider: dict,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list:
        from data.contracts import DataFetchError, ServiceUnavailableError

        command = self._format_history_command(
            provider['command'],
            {
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date,
            },
        )
        provider_label = (
            'MXDataAdapter history provider'
            if provider.get('legacy')
            else f"history provider {provider['name']}"
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=self.config.get('timeout', 10),
            )
        except UnicodeDecodeError as exc:
            raise DataFetchError(
                f"{provider_label} output is not valid UTF-8",
                error_code='INVALID_PROVIDER_RESPONSE',
                source='MXDataAdapter',
            ) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ServiceUnavailableError(
                f"{provider_label} failed: {exc}",
                error_code='REAL_HISTORY_PROVIDER_FAILED',
                source='MXDataAdapter',
            ) from exc

        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip()
            raise ServiceUnavailableError(
                f"{provider_label} exited with "
                f"{completed.returncode}: {error or '-'}",
                error_code='REAL_HISTORY_PROVIDER_FAILED',
                source='MXDataAdapter',
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise DataFetchError(
                f"{provider_label} output is not valid JSON",
                error_code='INVALID_PROVIDER_RESPONSE',
                source='MXDataAdapter',
            ) from exc

        if isinstance(payload, dict):
            payload = payload.get('history', payload.get('data'))
        if not isinstance(payload, list):
            raise DataFetchError(
                f"{provider_label} JSON must be a list or "
                'contain history/data list',
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
        providers = self.config.get('history_providers')
        if command and providers:
            return 'configure either history_command or history_providers, not both'
        if providers is not None and (
            not isinstance(providers, list)
            or not providers
        ):
            return 'history_providers must be a non-empty list'

        retry_attempts = self.config.get('history_retry_attempts', 1)
        if (
            not isinstance(retry_attempts, int)
            or isinstance(retry_attempts, bool)
            or retry_attempts <= 0
            or retry_attempts > self.MAX_HISTORY_RETRY_ATTEMPTS
        ):
            return (
                'history_retry_attempts must be an integer between 1 and '
                f'{self.MAX_HISTORY_RETRY_ATTEMPTS}'
            )
        retry_delay = self.config.get('history_retry_delay_seconds', 0)
        if (
            isinstance(retry_delay, bool)
            or not isinstance(retry_delay, Real)
            or not math.isfinite(float(retry_delay))
            or retry_delay < 0
            or retry_delay > self.MAX_HISTORY_RETRY_DELAY_SECONDS
        ):
            return (
                'history_retry_delay_seconds must be a finite number between '
                f'0 and {self.MAX_HISTORY_RETRY_DELAY_SECONDS}'
            )

        provider_configs = self._history_provider_configs()
        if not provider_configs:
            return 'real history provider not configured'

        names = set()
        for index, provider in enumerate(provider_configs):
            if not isinstance(provider, dict):
                return f'history_providers[{index}] must be an object'
            name = provider.get('name')
            if not isinstance(name, str) or not name.strip():
                return f'history_providers[{index}].name must be a non-empty string'
            if name in names:
                return f'history provider name is duplicated: {name}'
            names.add(name)

            error = self._command_error(
                provider.get('command'),
                validate_executable=not providers,
            )
            if error:
                if providers:
                    return f'history_providers[{index}].command {error}'
                return f'history_command {error}'
            if 'required_env' in provider:
                required_env_error = self._required_env_error(
                    provider.get('required_env'),
                )
                if required_env_error:
                    return (
                        f'history_providers[{index}].required_env '
                        f'{required_env_error}'
                    )
        return ''

    def _command_error(
        self,
        command,
        *,
        validate_executable: bool,
    ) -> str:
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            return 'must be a non-empty string list'

        for part in command:
            try:
                for _, field_name, format_spec, conversion in Formatter().parse(part):
                    if field_name is None:
                        continue
                    if field_name not in self.ALLOWED_HISTORY_PLACEHOLDERS:
                        return f'contains unknown placeholder: {field_name}'
                    if format_spec or conversion:
                        return 'placeholders do not support format specifiers'
            except ValueError as exc:
                return f'template invalid: {exc}'

        try:
            sample_command = self._format_history_command(
                command,
                {
                    'symbol': '510300',
                    'start_date': '2026-01-01',
                    'end_date': '2026-01-02',
                },
            )
        except (KeyError, ValueError) as exc:
            return f'template invalid: {exc}'

        if not validate_executable:
            return ''

        executable = sample_command[0]
        if self._is_path_like_command(executable):
            executable_path = Path(executable)
            if not executable_path.exists():
                return f'executable not found: {executable}'
            if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
                return f'executable is not executable: {executable}'
        elif shutil.which(executable) is None:
            return f'executable not found: {executable}'
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
            error_code = (
                'REAL_HISTORY_PROVIDER_ENV_MISSING'
                if self.last_error.startswith(
                    'history providers missing required environment variables:'
                )
                else 'ADAPTER_NOT_CONNECTED'
            )
            raise ServiceUnavailableError(
                self.last_error
                or 'MXDataAdapter real history provider is not connected',
                error_code=error_code,
                source='MXDataAdapter',
            )

    def _history_provider_configs(self) -> list[dict]:
        providers = self.config.get('history_providers')
        if isinstance(providers, list):
            return providers
        command = self.config.get('history_command')
        if command:
            return [{
                'name': 'default',
                'command': command,
                'legacy': True,
            }]
        return []

    def _format_history_command(
        self,
        command: list[str],
        values: dict,
    ) -> list[str]:
        return [
            part.format(**values)
            for part in command
        ]

    def _is_path_like_command(self, executable: str) -> bool:
        return (
            Path(executable).is_absolute()
            or '/' in executable
            or '\\' in executable
        )

    def _history_provider_statuses(self) -> list[dict]:
        return [
            {
                'name': provider['name'],
                'ready': not self._missing_provider_env(provider),
                'missing_env': self._missing_provider_env(provider),
            }
            for provider in self._history_provider_configs()
        ]

    def _missing_provider_env(self, provider: dict) -> list[str]:
        return [
            name
            for name in provider.get('required_env', [])
            if not os.environ.get(name)
        ]

    def _format_missing_provider_env(self, statuses: list[dict]) -> str:
        details = '; '.join(
            f"{status['name']}: {', '.join(status['missing_env'])}"
            for status in statuses
            if status['missing_env']
        )
        return (
            'history providers missing required environment variables: '
            f'{details}'
        )

    def _required_env_error(self, required_env) -> str:
        if (
            not isinstance(required_env, list)
            or not required_env
            or any(
                not isinstance(name, str) or not name.strip()
                for name in required_env
            )
        ):
            return 'must be a non-empty string list'
        if len(set(required_env)) != len(required_env):
            return 'must not contain duplicate names'
        return ''
