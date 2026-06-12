import math
from string import Formatter


MAX_HISTORY_RETRY_ATTEMPTS = 10
MAX_HISTORY_RETRY_DELAY_SECONDS = 60
ALLOWED_HISTORY_PLACEHOLDERS = frozenset({
    'symbol',
    'start_date',
    'end_date',
})


def validate_config(config: dict) -> dict:
    errors = []
    warnings = []
    if not isinstance(config, dict):
        return {
            'valid': False,
            'errors': ['配置必须是 dict'],
            'warnings': warnings,
        }

    _validate_required_sections(config, errors)
    _validate_data_config(config.get('data'), errors, warnings)
    _validate_account_config(config.get('account'), errors)
    _validate_risk_config(config.get('risk'), errors, warnings)
    _validate_monitor_config(config.get('monitor'), errors)
    _validate_state_config(config.get('state'), errors)
    if 'analysis' in config:
        _validate_analysis_config(config.get('analysis'), errors, warnings)

    return {
        'valid': not errors,
        'errors': errors,
        'warnings': warnings,
    }


def _validate_required_sections(config: dict, errors: list) -> None:
    for section in ('data', 'account', 'risk', 'monitor', 'state'):
        if section not in config:
            errors.append(f"缺少配置段: {section}")
        elif not isinstance(config[section], dict):
            errors.append(f"{section} 必须是 dict")


def _validate_data_config(data_config: dict | None, errors: list, warnings: list) -> None:
    if not isinstance(data_config, dict):
        return
    for key in ('max_realtime_age_seconds', 'max_nav_age_seconds'):
        _validate_optional_nullable_positive_number(
            data_config,
            key,
            f"data.{key}",
            errors,
        )
    _validate_optional_non_negative_number(
        data_config,
        'history_cache_ttl_seconds',
        'data.history_cache_ttl_seconds',
        errors,
    )
    _validate_optional_nullable_positive_number(
        data_config,
        'max_timestamp_future_skew_seconds',
        'data.max_timestamp_future_skew_seconds',
        errors,
    )
    _validate_optional_timezone_offset(
        data_config,
        'timestamp_timezone_offset',
        'data.timestamp_timezone_offset',
        errors,
    )
    for adapter_name in ('mx_data', 'mx_xuangu', 'mx_search'):
        adapter_config = data_config.get(adapter_name)
        _validate_adapter_config(
            adapter_config,
            f"data.{adapter_name}",
            errors,
            warnings,
            require_mode=True,
        )


def _validate_account_config(account_config: dict | None, errors: list) -> None:
    if not isinstance(account_config, dict):
        return
    _validate_positive_number(
        account_config.get('initial_capital'),
        'account.initial_capital',
        errors,
    )
    _validate_ratio(
        account_config.get('commission_rate'),
        'account.commission_rate',
        errors,
    )
    for key in ('buy_commission_rate', 'sell_commission_rate'):
        if key in account_config and account_config.get(key) is not None:
            _validate_ratio(
                account_config.get(key),
                f'account.{key}',
                errors,
            )
    if 'min_commission' in account_config:
        _validate_non_negative_number(
            account_config.get('min_commission'),
            'account.min_commission',
            errors,
        )


def _validate_risk_config(
    risk_config: dict | None,
    errors: list,
    warnings: list,
) -> None:
    if not isinstance(risk_config, dict):
        return
    _validate_positive_int(risk_config.get('max_position'), 'risk.max_position', errors)
    for key in ('stop_loss', 'max_single_loss'):
        _validate_ratio(risk_config.get(key), f"risk.{key}", errors)
    if 'trailing_stop' in risk_config and not isinstance(
        risk_config.get('trailing_stop'),
        bool,
    ):
        errors.append('risk.trailing_stop 必须是 bool')
    if 'trailing_pct' in risk_config:
        _validate_ratio(
            risk_config.get('trailing_pct'),
            'risk.trailing_pct',
            errors,
        )
    if 'max_single_weight' in risk_config:
        _validate_ratio(
            risk_config.get('max_single_weight'),
            'risk.max_single_weight',
            errors,
        )
    for key in ('min_volume', 'min_size', 'max_tracking_error', 'max_premium'):
        _validate_non_negative_number(risk_config.get(key), f"risk.{key}", errors)
    if 'mx_data' in risk_config:
        _validate_adapter_config(
            risk_config.get('mx_data'),
            'risk.mx_data',
            errors,
            warnings,
            require_mode=False,
        )


def _validate_monitor_config(monitor_config: dict | None, errors: list) -> None:
    if not isinstance(monitor_config, dict):
        return
    _validate_positive_number(
        monitor_config.get('check_interval'),
        'monitor.check_interval',
        errors,
    )
    _validate_number(
        monitor_config.get('alert_threshold'),
        'monitor.alert_threshold',
        errors,
    )
    if 'max_position' in monitor_config:
        _validate_positive_int(
            monitor_config.get('max_position'),
            'monitor.max_position',
            errors,
        )
    alert_file_path = monitor_config.get('alert_file_path')
    if alert_file_path is not None and not isinstance(alert_file_path, str):
        errors.append('monitor.alert_file_path 必须是字符串或 null')


def _validate_state_config(state_config: dict | None, errors: list) -> None:
    if not isinstance(state_config, dict):
        return
    for key in ('enabled', 'restore_on_start', 'save_on_stop'):
        if not isinstance(state_config.get(key), bool):
            errors.append(f"state.{key} 必须是 bool")
    if state_config.get('enabled') and not state_config.get('path'):
        errors.append('state.path 不能为空')
    elif (
        state_config.get('path') is not None
        and not isinstance(state_config.get('path'), str)
    ):
        errors.append('state.path 必须是字符串')


def _validate_analysis_config(
    analysis_config: dict | None,
    errors: list,
    warnings: list,
) -> None:
    if not isinstance(analysis_config, dict):
        errors.append('analysis 必须是 dict')
        return
    if 'jason_kb' in analysis_config:
        _validate_adapter_config(
            analysis_config.get('jason_kb'),
            'analysis.jason_kb',
            errors,
            warnings,
            require_mode=False,
        )


def _validate_adapter_config(
    adapter_config: dict | None,
    name: str,
    errors: list,
    warnings: list,
    *,
    require_mode: bool,
) -> None:
    if not isinstance(adapter_config, dict):
        errors.append(f"{name} 必须是 dict")
        return

    mode = adapter_config.get('mode')
    if mode is None and not require_mode:
        mode = 'mock'
    if mode not in ('mock', 'real'):
        errors.append(f"{name}.mode 必须是 mock 或 real")
    elif mode == 'real':
        if name == 'data.mx_data' and (
            adapter_config.get('history_command')
            or adapter_config.get('history_providers')
        ):
            warnings.append(
                'data.mx_data.mode=real 当前仅支持命令式历史行情 provider'
            )
        else:
            warnings.append(f"{name}.mode=real 当前仍是未实现适配器")

    if name == 'data.mx_data' and 'history_command' in adapter_config:
        history_command = adapter_config.get('history_command')
        if history_command is not None and (
            not isinstance(history_command, list)
            or not history_command
            or any(
                not isinstance(part, str) or not part
                for part in history_command
            )
        ):
            errors.append('data.mx_data.history_command 必须是非空字符串数组')
        elif history_command is not None:
            _validate_history_command_template(
                history_command,
                'data.mx_data.history_command',
                errors,
            )

    if name == 'data.mx_data':
        _validate_history_providers(adapter_config, errors)
        if (
            adapter_config.get('history_command')
            and adapter_config.get('history_providers')
        ):
            errors.append(
                'data.mx_data.history_command 与 history_providers 不能同时配置'
            )
        _validate_optional_positive_int(
            adapter_config,
            'history_retry_attempts',
            'data.mx_data.history_retry_attempts',
            errors,
            maximum=MAX_HISTORY_RETRY_ATTEMPTS,
        )
        _validate_optional_non_negative_number(
            adapter_config,
            'history_retry_delay_seconds',
            'data.mx_data.history_retry_delay_seconds',
            errors,
            maximum=MAX_HISTORY_RETRY_DELAY_SECONDS,
        )

    _validate_optional_positive_number(
        adapter_config,
        'timeout',
        f"{name}.timeout",
        errors,
    )


def _validate_history_providers(adapter_config: dict, errors: list) -> None:
    if 'history_providers' not in adapter_config:
        return
    providers = adapter_config.get('history_providers')
    if providers is None:
        return
    if not isinstance(providers, list) or not providers:
        errors.append('data.mx_data.history_providers 必须是非空数组或 null')
        return

    names = set()
    for index, provider in enumerate(providers):
        prefix = f'data.mx_data.history_providers[{index}]'
        if not isinstance(provider, dict):
            errors.append(f'{prefix} 必须是 dict')
            continue
        name = provider.get('name')
        if not isinstance(name, str) or not name.strip():
            errors.append(f'{prefix}.name 必须是非空字符串')
        elif name in names:
            errors.append(f'data.mx_data.history_providers.name 不能重复: {name}')
        else:
            names.add(name)
        command = provider.get('command')
        if (
            not isinstance(command, list)
            or not command
            or any(
                not isinstance(part, str) or not part
                for part in command
            )
        ):
            errors.append(f'{prefix}.command 必须是非空字符串数组')
        else:
            _validate_history_command_template(
                command,
                f'{prefix}.command',
                errors,
            )


def _validate_history_command_template(
    command: list[str],
    name: str,
    errors: list,
) -> None:
    for part in command:
        try:
            parsed = Formatter().parse(part)
            for _, field_name, format_spec, conversion in parsed:
                if field_name is None:
                    continue
                if field_name not in ALLOWED_HISTORY_PLACEHOLDERS:
                    errors.append(f'{name} 包含未知占位符: {field_name}')
                    return
                if format_spec or conversion:
                    errors.append(f'{name} 不支持占位符格式化参数')
                    return
        except ValueError as exc:
            errors.append(f'{name} 模板无效: {exc}')
            return


def _validate_positive_number(value, name: str, errors: list) -> None:
    if not _is_number(value) or value <= 0:
        errors.append(f"{name} 必须大于 0")


def _validate_optional_positive_number(
    config: dict,
    key: str,
    name: str,
    errors: list,
) -> None:
    if key in config:
        _validate_positive_number(config.get(key), name, errors)


def _validate_optional_non_negative_number(
    config: dict,
    key: str,
    name: str,
    errors: list,
    maximum=None,
) -> None:
    if key in config:
        value = config.get(key)
        before = len(errors)
        _validate_non_negative_number(value, name, errors)
        if (
            len(errors) == before
            and maximum is not None
            and value > maximum
        ):
            errors.append(f"{name} 不能大于 {maximum}")


def _validate_optional_positive_int(
    config: dict,
    key: str,
    name: str,
    errors: list,
    maximum=None,
) -> None:
    if key in config:
        value = config.get(key)
        before = len(errors)
        _validate_positive_int(value, name, errors)
        if (
            len(errors) == before
            and maximum is not None
            and value > maximum
        ):
            errors.append(f"{name} 不能大于 {maximum}")


def _validate_optional_nullable_positive_number(
    config: dict,
    key: str,
    name: str,
    errors: list,
) -> None:
    if key in config and config.get(key) is not None:
        _validate_positive_number(config.get(key), name, errors)


def _validate_optional_timezone_offset(
    config: dict,
    key: str,
    name: str,
    errors: list,
) -> None:
    if key not in config:
        return
    value = config.get(key)
    if not isinstance(value, str):
        errors.append(f"{name} 必须是 +HH:MM 或 -HH:MM")
        return
    if len(value) != 6 or value[0] not in '+-' or value[3] != ':':
        errors.append(f"{name} 必须是 +HH:MM 或 -HH:MM")
        return
    try:
        hours = int(value[1:3])
        minutes = int(value[4:6])
    except ValueError:
        errors.append(f"{name} 必须是 +HH:MM 或 -HH:MM")
        return
    if hours > 23 or minutes > 59:
        errors.append(f"{name} 超出合法时区偏移范围")


def _validate_non_negative_number(value, name: str, errors: list) -> None:
    if not _is_number(value) or value < 0:
        errors.append(f"{name} 不能小于 0")


def _validate_positive_int(value, name: str, errors: list) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{name} 必须是正整数")


def _validate_ratio(value, name: str, errors: list) -> None:
    if not _is_number(value) or value < 0 or value > 1:
        errors.append(f"{name} 必须在 0 到 1 之间")


def _validate_number(value, name: str, errors: list) -> None:
    if not _is_number(value):
        errors.append(f"{name} 必须是数字")


def _is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    if not isinstance(value, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
