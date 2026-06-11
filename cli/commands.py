import argparse
import json
import math
import sys
import os
import tempfile
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.runner import (
    BacktestRunner,
    RotationBacktestRunner,
    filter_history_by_date,
    load_history_csv,
    load_rotation_history_csv,
    load_rotation_history_json,
    sample_grid_history,
    sample_rotation_history,
    write_equity_curve_csv,
    write_markdown_report,
    write_portfolio_csv,
    write_positions_csv,
    write_rejected_orders_csv,
    write_trades_csv,
)
from backtest.history_adapter import (
    build_rotation_history,
    fetch_grid_history,
    fetch_rotation_history,
    write_grid_history_csv,
    write_rotation_history_csv,
)
from backtest.trading_calendar import TradingCalendar
from main import QuantPipeline
from config.settings import SYSTEM_CONFIG
from config.validation import validate_config
from data.contracts import AdapterError
from data.data_manager import DataManager
from persistence import JsonStateStore
from strategy.grid_strategy import GridStrategy
from strategy.rotation_strategy import RotationStrategy


DEFAULT_BACKTEST_SYMBOL = '510300'
DEFAULT_BACKTEST_CENTER_PRICE = 4.00
DEFAULT_BACKTEST_GRID_SIZE = 0.10
DEFAULT_BACKTEST_GRID_COUNT = 5
DEFAULT_BACKTEST_SHARES_PER_GRID = 1000
DEFAULT_BACKTEST_INITIAL_CAPITAL = 100000
DEFAULT_BACKTEST_COMMISSION_RATE = 0.0003
DEFAULT_BACKTEST_MIN_COMMISSION = 0.0
DEFAULT_BACKTEST_SLIPPAGE_RATE = 0.0
DEFAULT_BACKTEST_MAX_VOLUME_PARTICIPATION = None
DEFAULT_BACKTEST_ETF_POOL = ['510300', '510500', '159915']
DEFAULT_BACKTEST_ROTATION_LOOKBACK = 3
DEFAULT_BACKTEST_ROTATION_TOP_N = 1
DEFAULT_BACKTEST_ROTATION_REBALANCE_DAYS = 0
DEFAULT_ALERT_FILE_PATH = 'data/alerts.jsonl'


def cmd_start(args):
    system = QuantPipeline(_build_runtime_config(args))

    if args.strategy == 'grid':
        strategy = GridStrategy({
            'name': '网格策略',
            'symbol': args.symbol or '510300',
            'center_price': args.center_price or 4.00,
            'grid_size': args.grid_size or 0.10,
            'grid_count': args.grid_count or 5,
            'capital_per_grid': args.capital or 10000,
        })
        system.add_strategy(strategy)
    elif args.strategy == 'rotation':
        etf_pool = args.etf_pool.split(',') if args.etf_pool else ['510300', '510500', '159915', '512100']
        strategy = RotationStrategy({
            'name': '行业轮动',
            'symbol': etf_pool[0],  # 主 symbol
            'etf_pool': etf_pool,
            'lookback': args.lookback or 20,
            'top_n': args.top_n or 2,
            'rebalance_days': args.rebalance_days or 30,
        })
        system.add_strategy(strategy)

    system.run()


def cmd_status(args):
    system = QuantPipeline(_build_runtime_config(args))
    system.restore_state()
    status = system.get_status()
    print(f"资金: {status['portfolio'].get('capital', 0):.2f}")
    print(f"持仓: {status['portfolio'].get('position_count', 0)}")
    print(f"总价值: {status['portfolio'].get('total_value', 0):.2f}")
    print(f"盈亏: {status['portfolio'].get('pnl', 0):.2f}")


def cmd_report(args):
    system = QuantPipeline(_build_runtime_config(args))
    system.restore_state()
    report = system.generate_report(args.type or 'daily')
    print(report)


def cmd_health(args):
    system = QuantPipeline(_build_runtime_config(args))
    try:
        system.data_manager.connect()
        summary = _build_health_summary(system.data_manager.health_check())
    finally:
        system.data_manager.disconnect()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(_render_health_summary(summary))

    if args.strict and not summary['available']:
        raise SystemExit(1)


def cmd_alerts(args):
    events = _load_alert_events(args.alert_file, args.limit)
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(_render_alert_events(events))


def cmd_config_validate(args):
    config = _load_config_file(args.config) if args.config else deepcopy(SYSTEM_CONFIG)
    result = validate_config(config)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_render_config_validation(result))
    if not result['valid']:
        raise SystemExit(1)


def cmd_config_show(args):
    config = (
        _load_config_file(args.config)
        if args.config
        else deepcopy(SYSTEM_CONFIG)
    )
    print(json.dumps(config, ensure_ascii=False, indent=2))


def _unlink_if_present(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def cmd_config_init(args):
    output_path = _resolve_project_path(args.output)
    if output_path.exists() and not output_path.is_file():
        raise ValueError(f'配置输出路径不是文件: {output_path}')
    if output_path.exists() and not args.force:
        raise ValueError(f'配置文件已存在，使用 --force 覆盖: {output_path}')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=output_path.parent,
            prefix=f'.{output_path.name}.',
            suffix='.tmp',
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(
                json.dumps(SYSTEM_CONFIG, ensure_ascii=False, indent=2) + '\n'
            )
        temp_path.replace(output_path)
    finally:
        if temp_path is not None:
            _unlink_if_present(temp_path)
    print(f'配置模板: {output_path}')


def cmd_diagnose(args):
    config = _build_diagnostic_config(args)
    report = _build_diagnostic_report(config)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_diagnostic_report(report))

    if args.strict and not report['ready']:
        raise SystemExit(1)


def cmd_history_export_grid(args):
    history = (
        _load_history_json_list(args.input_json)
        if args.input_json
        else _fetch_grid_history_from_data_manager(args)
    )
    output_path = write_grid_history_csv(
        str(_resolve_project_path(args.output)),
        history,
    )
    print(f"grid 历史 CSV: {output_path}")


def cmd_history_export_rotation(args):
    lookback = _positive_int(
        _value_or_default(args.lookback, DEFAULT_BACKTEST_ROTATION_LOOKBACK),
        '--lookback',
    )
    history = (
        build_rotation_history(
            _load_history_json_object(args.input_json),
            lookback=lookback,
        )
        if args.input_json
        else _fetch_rotation_history_from_data_manager(args, lookback)
    )
    output_path = write_rotation_history_csv(
        str(_resolve_project_path(args.output)),
        history,
    )
    print(f"rotation 历史 CSV: {output_path}")


def cmd_history_probe(args):
    _require_date_range(args)
    symbol = _resolve_symbol(args.symbol)
    data_manager = DataManager(_load_history_data_config(args))
    try:
        data_manager.connect()
        history = fetch_grid_history(
            data_manager,
            symbol,
            args.start_date,
            args.end_date,
        )
    finally:
        data_manager.disconnect()
    validated_history = _validate_history_probe_range(
        history,
        args.start_date,
        args.end_date,
    )

    result = {
        'available': True,
        'symbol': symbol,
        'start_date': args.start_date,
        'end_date': args.end_date,
        'row_count': len(validated_history),
        'first_date': validated_history[0]['date'],
        'last_date': validated_history[-1]['date'],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_render_history_probe(result))


def cmd_backtest(args):
    initial_capital = _positive_number(
        _value_or_default(args.initial_capital, DEFAULT_BACKTEST_INITIAL_CAPITAL),
        '--initial-capital',
    )
    commission_rate = _commission_rate(
        _value_or_default(args.commission_rate, DEFAULT_BACKTEST_COMMISSION_RATE),
        '--commission-rate',
    )
    buy_commission_rate = _commission_rate(
        _value_or_default(args.buy_commission_rate, commission_rate),
        '--buy-commission-rate',
    )
    sell_commission_rate = _commission_rate(
        _value_or_default(args.sell_commission_rate, commission_rate),
        '--sell-commission-rate',
    )
    min_commission = _non_negative_number(
        _value_or_default(args.min_commission, DEFAULT_BACKTEST_MIN_COMMISSION),
        '--min-commission',
    )
    slippage_rate = _slippage_rate(
        _value_or_default(args.slippage_rate, DEFAULT_BACKTEST_SLIPPAGE_RATE),
        '--slippage-rate',
    )
    max_volume_participation = _volume_participation(
        _value_or_default(
            args.max_volume_participation,
            DEFAULT_BACKTEST_MAX_VOLUME_PARTICIPATION,
        ),
        '--max-volume-participation',
    )
    trading_calendar = _build_trading_calendar(args)
    account_config = {
        'initial_capital': initial_capital,
        'commission_rate': commission_rate,
        'buy_commission_rate': buy_commission_rate,
        'sell_commission_rate': sell_commission_rate,
        'min_commission': min_commission,
        'slippage_rate': slippage_rate,
        'max_volume_participation': max_volume_participation,
    }

    if args.strategy == 'grid':
        _run_grid_backtest(
            args,
            account_config,
            trading_calendar,
        )
    elif args.strategy == 'rotation':
        _run_rotation_backtest(
            args,
            account_config,
            trading_calendar,
        )


def _run_grid_backtest(
    args,
    account_config: dict,
    trading_calendar: TradingCalendar | None,
):
    symbol = _resolve_symbol(args.symbol)
    center_price = _positive_number(
        _value_or_default(args.center_price, DEFAULT_BACKTEST_CENTER_PRICE),
        '--center-price',
    )
    grid_size = _positive_number(
        _value_or_default(args.grid_size, DEFAULT_BACKTEST_GRID_SIZE),
        '--grid-size',
    )
    grid_count = _positive_int(
        _value_or_default(args.grid_count, DEFAULT_BACKTEST_GRID_COUNT),
        '--grid-count',
    )
    shares_per_grid = _positive_int(
        _value_or_default(args.shares_per_grid, DEFAULT_BACKTEST_SHARES_PER_GRID),
        '--shares-per-grid',
    )
    max_grids = _positive_int(
        _value_or_default(args.max_grids, grid_count),
        '--max-grids',
    )

    strategy = GridStrategy({
        'name': '网格回测',
        'symbol': symbol,
        'center_price': center_price,
        'grid_size': grid_size,
        'grid_count': grid_count,
        'shares_per_grid': shares_per_grid,
        'max_grids': max_grids,
    })
    history = _resolve_backtest_history(
        load_history_csv(args.history) if args.history else sample_grid_history(),
        args,
    )
    runner = BacktestRunner(
        strategy,
        account_config,
        trading_calendar=trading_calendar,
    )
    result = runner.run(history)
    report = runner.render_markdown(result)
    print(report)
    _write_backtest_outputs(args, result, report)


def _run_rotation_backtest(
    args,
    account_config: dict,
    trading_calendar: TradingCalendar | None,
):
    etf_pool = _resolve_etf_pool(args.etf_pool)
    history = _resolve_backtest_history(
        _load_rotation_history(args.history),
        args,
    )
    available_symbols = set(history[0].get('symbols', {}))
    missing_symbols = [symbol for symbol in etf_pool if symbol not in available_symbols]
    if missing_symbols:
        source_label = '历史 JSON' if args.history else '内置样例'
        raise ValueError(
            f"rotation {source_label}不包含 ETF: {', '.join(missing_symbols)}"
        )
    lookback = _positive_int(
        _value_or_default(args.lookback, DEFAULT_BACKTEST_ROTATION_LOOKBACK),
        '--lookback',
    )
    top_n = _positive_int(
        _value_or_default(args.top_n, DEFAULT_BACKTEST_ROTATION_TOP_N),
        '--top-n',
    )
    rebalance_days = _non_negative_int(
        _value_or_default(args.rebalance_days, DEFAULT_BACKTEST_ROTATION_REBALANCE_DAYS),
        '--rebalance-days',
    )
    if top_n > len(etf_pool):
        raise ValueError('--top-n 不能大于 ETF 池数量')

    strategy = RotationStrategy({
        'name': '轮动回测',
        'symbol': etf_pool[0],
        'etf_pool': etf_pool,
        'lookback': lookback,
        'top_n': top_n,
        'rebalance_days': rebalance_days,
    })
    runner = RotationBacktestRunner(
        strategy,
        account_config,
        trading_calendar=trading_calendar,
    )
    result = runner.run(history)
    report = runner.render_markdown(result)
    print(report)
    _write_backtest_outputs(args, result, report)


def _resolve_symbol(symbol: str) -> str:
    resolved = symbol.strip() if symbol else DEFAULT_BACKTEST_SYMBOL
    if not resolved:
        raise ValueError('--symbol 不能为空')
    return resolved


def _load_rotation_history(history_path: str | None) -> list:
    if not history_path:
        return sample_rotation_history()
    if Path(history_path).suffix.lower() == '.json':
        return load_rotation_history_json(history_path)
    return load_rotation_history_csv(history_path)


def _resolve_etf_pool(etf_pool: str) -> list:
    if not etf_pool:
        return list(DEFAULT_BACKTEST_ETF_POOL)
    symbols = [symbol.strip() for symbol in etf_pool.split(',') if symbol.strip()]
    if not symbols:
        raise ValueError('--etf-pool 不能为空')
    return symbols


def _resolve_backtest_history(history: list, args) -> list:
    return filter_history_by_date(
        history,
        start_date=args.start_date,
        end_date=args.end_date,
    )


def _fetch_grid_history_from_data_manager(args) -> list:
    _require_date_range(args)
    data_manager = DataManager(_load_history_data_config(args))
    try:
        data_manager.connect()
        return fetch_grid_history(
            data_manager,
            _resolve_symbol(args.symbol),
            args.start_date,
            args.end_date,
        )
    finally:
        data_manager.disconnect()


def _fetch_rotation_history_from_data_manager(args, lookback: int) -> list:
    _require_date_range(args)
    symbols = _resolve_etf_pool(args.etf_pool)
    data_manager = DataManager(_load_history_data_config(args))
    try:
        data_manager.connect()
        return fetch_rotation_history(
            data_manager,
            symbols,
            args.start_date,
            args.end_date,
            lookback=lookback,
        )
    finally:
        data_manager.disconnect()


def _require_date_range(args) -> None:
    if not args.start_date or not args.end_date:
        raise ValueError('未提供 --input-json 时必须指定 --start-date 和 --end-date')


def _validate_history_probe_range(
    history: list,
    start_date: str,
    end_date: str,
) -> list:
    ordered_history = filter_history_by_date(history)
    try:
        filtered_history = filter_history_by_date(
            ordered_history,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        if str(exc) == '指定日期区间内没有历史行情':
            raise ValueError('历史 provider 返回了请求区间外的数据') from exc
        raise
    if len(filtered_history) != len(ordered_history):
        raise ValueError('历史 provider 返回了请求区间外的数据')
    return filtered_history


def _load_history_data_config(args) -> dict:
    if not getattr(args, 'config', None):
        return deepcopy(SYSTEM_CONFIG.get('data', {}))
    config = _load_config_file(args.config)
    data_config = config.get('data')
    if not isinstance(data_config, dict):
        raise TypeError('配置文件缺少 data 对象')
    return data_config


def _load_history_json_list(path: str) -> list:
    payload = _load_json_file(path)
    if not isinstance(payload, list):
        raise ValueError('grid 历史 JSON 顶层必须是数组')
    return payload


def _load_history_json_object(path: str) -> dict:
    payload = _load_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError('rotation 历史 JSON 顶层必须是 symbol->history 对象')
    return payload


def _load_json_file(path: str):
    resolved = _resolve_project_path(path)
    try:
        return json.loads(resolved.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError(f"JSON 文件不存在: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 文件不是合法 JSON: {exc.msg}") from exc


def _build_trading_calendar(args) -> TradingCalendar | None:
    holidays = args.holiday or []
    extra_trading_days = args.trading_day or []
    if not args.strict_trading_calendar:
        if holidays or extra_trading_days:
            raise ValueError(
                '--holiday/--trading-day 需要同时启用 --strict-trading-calendar'
            )
        return None
    return TradingCalendar(
        holidays=holidays,
        extra_trading_days=extra_trading_days,
    )


def _write_backtest_outputs(args, result: dict, report: str) -> None:
    if args.report_output:
        report_path = write_markdown_report(
            str(_resolve_project_path(args.report_output)),
            report,
        )
        print(f"回测报告 Markdown: {report_path}")
    if args.equity_output:
        equity_path = write_equity_curve_csv(
            str(_resolve_project_path(args.equity_output)),
            result['equity_curve'],
        )
        print(f"权益曲线 CSV: {equity_path}")
    if args.portfolio_output:
        portfolio_path = write_portfolio_csv(
            str(_resolve_project_path(args.portfolio_output)),
            result['portfolio_curve'],
        )
        print(f"组合快照 CSV: {portfolio_path}")
    if args.trades_output:
        trades_path = write_trades_csv(
            str(_resolve_project_path(args.trades_output)),
            result['trades'],
        )
        print(f"成交明细 CSV: {trades_path}")
    if args.positions_output:
        positions_path = write_positions_csv(
            str(_resolve_project_path(args.positions_output)),
            result['positions_curve'],
        )
        print(f"持仓明细 CSV: {positions_path}")
    if args.rejections_output:
        rejections_path = write_rejected_orders_csv(
            str(_resolve_project_path(args.rejections_output)),
            result['rejected_orders'],
        )
        print(f"拒单明细 CSV: {rejections_path}")


def _value_or_default(value, default):
    return default if value is None else value


def _positive_number(value: float, option_name: str) -> float:
    if value <= 0:
        raise ValueError(f"{option_name} 必须大于 0")
    return value


def _positive_int(value: int, option_name: str) -> int:
    if value <= 0:
        raise ValueError(f"{option_name} 必须大于 0")
    return value


def _non_negative_int(value: int, option_name: str) -> int:
    if value < 0:
        raise ValueError(f"{option_name} 不能小于 0")
    return value


def _non_negative_number(value: float, option_name: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{option_name} 不能小于 0")
    return value


def _commission_rate(value: float, option_name: str) -> float:
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError(f"{option_name} 必须在 0 到 1 之间")
    return value


def _slippage_rate(value: float, option_name: str) -> float:
    if not math.isfinite(value) or value < 0 or value >= 1:
        raise ValueError(f"{option_name} 必须在 0 到 1 之间，且小于 1")
    return value


def _volume_participation(
    value: float | None,
    option_name: str,
) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value <= 0 or value > 1:
        raise ValueError(f"{option_name} 必须大于 0 且不大于 1")
    return value


def _build_runtime_config(args) -> dict:
    config = deepcopy(SYSTEM_CONFIG)
    state_config = config.setdefault('state', {})
    if getattr(args, 'no_state', False):
        state_config['enabled'] = False
    if getattr(args, 'state_path', None):
        state_config['path'] = args.state_path
    return config


def _build_diagnostic_config(args) -> dict:
    config = (
        _load_config_file(args.config)
        if getattr(args, 'config', None)
        else deepcopy(SYSTEM_CONFIG)
    )
    state_config = config.get('state')
    if isinstance(state_config, dict):
        if getattr(args, 'no_state', False):
            state_config['enabled'] = False
        if getattr(args, 'state_path', None):
            state_config['path'] = args.state_path
    return config


def _build_diagnostic_report(config: dict) -> dict:
    config_result = validate_config(config)
    data_summary = _diagnose_data_sources(config)
    state_summary = _diagnose_state(config)
    return {
        'ready': (
            config_result['valid']
            and data_summary['available']
            and state_summary['ok']
        ),
        'config': config_result,
        'data': data_summary,
        'state': state_summary,
    }


def _diagnose_data_sources(config: dict) -> dict:
    data_config = config.get('data')
    if not isinstance(data_config, dict):
        return {
            'available': False,
            'mock': False,
            'adapters': {},
            'error': 'data 必须是 dict',
        }
    try:
        manager = DataManager(data_config)
    except (AttributeError, TypeError, ValueError) as exc:
        return {
            'available': False,
            'mock': False,
            'adapters': {},
            'error': str(exc),
        }
    try:
        manager.connect()
        return _build_health_summary(manager.health_check())
    finally:
        manager.disconnect()


def _diagnose_state(config: dict) -> dict:
    state_config = config.get('state')
    if not isinstance(state_config, dict):
        return {
            'enabled': False,
            'path': None,
            'exists': False,
            'has_data': False,
            'ok': False,
            'version': None,
            'error': 'state 必须是 dict',
        }
    if not state_config.get('enabled', False):
        return {
            'enabled': False,
            'path': None,
            'exists': False,
            'has_data': False,
            'ok': True,
            'version': None,
            'error': '',
        }

    configured_path = state_config.get('path', 'data/state.json')
    if not isinstance(configured_path, str) or not configured_path:
        return {
            'enabled': True,
            'path': None,
            'exists': False,
            'has_data': False,
            'ok': False,
            'version': None,
            'error': 'state.path 必须是非空字符串',
        }
    store = JsonStateStore(configured_path)
    try:
        state = store.load_state()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            'enabled': True,
            'path': str(store.path),
            'exists': store.path.exists(),
            'has_data': False,
            'ok': False,
            'version': None,
            'error': str(exc),
        }
    return {
        'enabled': True,
        'path': str(store.path),
        'exists': store.path.exists(),
        'has_data': _state_has_data(state),
        'ok': True,
        'version': state.get('version') if state else None,
        'error': '',
    }


def _state_has_data(state: dict) -> bool:
    return any(
        value not in (None, '', [], {})
        for key, value in state.items()
        if key != 'version'
    )


def _build_health_summary(adapter_statuses: dict) -> dict:
    return {
        'available': bool(adapter_statuses) and all(
            status.get('available', False)
            for status in adapter_statuses.values()
        ),
        'mock': bool(adapter_statuses) and all(
            status.get('mock', False)
            for status in adapter_statuses.values()
        ),
        'adapters': adapter_statuses,
    }


def _render_health_summary(summary: dict) -> str:
    overall = 'OK' if summary['available'] else 'FAIL'
    mode = 'mock' if summary['mock'] else 'mixed/real'
    lines = [f"数据源状态: {overall} ({mode})"]
    if summary.get('error'):
        lines.append(f"- error: {summary['error']}")
    for name, status in summary['adapters'].items():
        availability = '可用' if status.get('available') else '不可用'
        error = status.get('error') or '-'
        lines.append(
            f"- {name}: {availability}, mode={status.get('mode')}, "
            f"service={status.get('service')}, error={error}"
        )
    return "\n".join(lines)


def _load_alert_events(alert_file: str | None, limit: int) -> list:
    if limit < 0:
        raise ValueError('--limit 不能小于 0')

    path = _resolve_project_path(alert_file or _default_alert_file_path())
    if not path.exists():
        return []

    events = []
    for line_number, line in enumerate(
        path.read_text(encoding='utf-8').splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"告警文件第 {line_number} 行不是合法 JSON: {exc.msg}"
            ) from exc
        if not isinstance(event, dict):
            raise ValueError(f"告警文件第 {line_number} 行必须是 JSON object")
        events.append(event)

    if limit == 0:
        return []
    return events[-limit:]


def _render_alert_events(events: list) -> str:
    if not events:
        return "告警事件: 无"

    lines = [f"告警事件: {len(events)} 条"]
    for event in events:
        level = event.get('level', 'warning')
        category = event.get('category', 'system')
        message = event.get('message', '')
        timestamp = event.get('timestamp') or '-'
        lines.append(f"- [{level}] {category}: {message} ({timestamp})")
    return "\n".join(lines)


def _default_alert_file_path() -> str:
    return (
        SYSTEM_CONFIG.get('monitor', {}).get('alert_file_path')
        or DEFAULT_ALERT_FILE_PATH
    )


def _resolve_project_path(path: str) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / resolved


def _load_config_file(config_path: str) -> dict:
    path = _resolve_project_path(config_path)
    try:
        config = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError(f"配置文件不存在: {path}") from exc
    except OSError as exc:
        raise ValueError(f"配置文件无法读取: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是合法 JSON: {exc.msg}") from exc
    if not isinstance(config, dict):
        raise TypeError('配置文件顶层必须是 JSON object')
    return config


def _render_config_validation(result: dict) -> str:
    status = 'OK' if result['valid'] else 'FAIL'
    lines = [f"配置校验: {status}"]
    if result['errors']:
        lines.append("错误:")
        lines.extend(f"- {error}" for error in result['errors'])
    if result['warnings']:
        lines.append("警告:")
        lines.extend(f"- {warning}" for warning in result['warnings'])
    return "\n".join(lines)


def _render_diagnostic_report(report: dict) -> str:
    overall = 'OK' if report['ready'] else 'FAIL'
    lines = [f"运行诊断: {overall}"]
    lines.append(_render_config_validation(report['config']))
    lines.append(_render_health_summary(report['data']))
    lines.append(_render_state_summary(report['state']))
    return "\n".join(lines)


def _render_state_summary(summary: dict) -> str:
    if not summary['enabled']:
        return '状态文件: OK (disabled)'
    if not summary['ok']:
        return f"状态文件: FAIL, path={summary['path']}, error={summary['error']}"
    if not summary['exists']:
        return f"状态文件: OK (missing), path={summary['path']}"
    if not summary['has_data']:
        return f"状态文件: OK (empty), path={summary['path']}"
    return (
        f"状态文件: OK, path={summary['path']}, version={summary.get('version')}"
    )


def _render_history_probe(result: dict) -> str:
    return (
        f"历史 provider: OK, symbol={result['symbol']}, "
        f"request={result['start_date']}..{result['end_date']}, "
        f"rows={result['row_count']}, "
        f"data={result['first_date']}..{result['last_date']}"
    )


def _add_state_options(parser):
    parser.add_argument('--state-path', type=str, help='状态文件路径，默认 data/state.json')
    parser.add_argument('--no-state', action='store_true', help='禁用状态恢复和保存')


def main():
    parser = argparse.ArgumentParser(description='量化助手 Pipeline CLI')
    subparsers = parser.add_subparsers(dest='command')

    start_parser = subparsers.add_parser('start', help='启动策略')
    start_parser.add_argument('--strategy', default='grid', choices=['grid', 'rotation'])
    start_parser.add_argument('--symbol', type=str)
    start_parser.add_argument('--center-price', type=float)
    start_parser.add_argument('--grid-size', type=float)
    start_parser.add_argument('--grid-count', type=int)
    start_parser.add_argument('--capital', type=float)
    start_parser.add_argument('--etf-pool', type=str, help='ETF池，逗号分隔')
    start_parser.add_argument('--lookback', type=int, help='回看周期')
    start_parser.add_argument('--top-n', type=int, help='选择ETF数量')
    start_parser.add_argument('--rebalance-days', type=int, help='再平衡天数')
    _add_state_options(start_parser)

    status_parser = subparsers.add_parser('status', help='查看状态')
    _add_state_options(status_parser)

    report_parser = subparsers.add_parser('report', help='生成报告')
    report_parser.add_argument('--type', default='daily', choices=['daily', 'weekly'])
    _add_state_options(report_parser)

    health_parser = subparsers.add_parser('health', help='检查数据源健康状态')
    health_parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    health_parser.add_argument(
        '--strict',
        action='store_true',
        help='任一数据源不可用时返回非零退出码',
    )
    _add_state_options(health_parser)

    diagnose_parser = subparsers.add_parser('diagnose', help='运行启动前诊断')
    diagnose_parser.add_argument('--config', type=str, help='JSON 配置文件路径，默认使用内置配置')
    diagnose_parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    diagnose_parser.add_argument(
        '--strict',
        action='store_true',
        help='任一诊断项失败时返回非零退出码',
    )
    _add_state_options(diagnose_parser)

    alerts_parser = subparsers.add_parser('alerts', help='查看本地告警事件')
    alerts_parser.add_argument(
        '--alert-file',
        type=str,
        help='告警 JSONL 文件路径，默认读取 monitor.alert_file_path 或 data/alerts.jsonl',
    )
    alerts_parser.add_argument('--limit', type=int, default=10, help='显示最近 N 条告警，默认 10')
    alerts_parser.add_argument('--json', action='store_true', help='输出 JSON 格式')

    config_parser = subparsers.add_parser('config', help='配置工具')
    config_subparsers = config_parser.add_subparsers(dest='config_command')
    validate_parser = config_subparsers.add_parser('validate', help='校验配置')
    validate_parser.add_argument(
        '--config',
        type=str,
        help='JSON 配置文件路径，默认校验内置配置',
    )
    validate_parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    show_parser = config_subparsers.add_parser('show', help='显示有效配置')
    show_parser.add_argument(
        '--config',
        type=str,
        help='JSON 配置文件路径，默认显示内置配置',
    )
    init_parser = config_subparsers.add_parser('init', help='生成默认配置模板')
    init_parser.add_argument(
        '--output',
        type=str,
        default='config.local.json',
        help='输出路径，默认 config.local.json',
    )
    init_parser.add_argument(
        '--force',
        action='store_true',
        help='覆盖已有配置文件',
    )

    history_parser = subparsers.add_parser('history', help='历史数据转换工具')
    history_subparsers = history_parser.add_subparsers(dest='history_command')
    history_probe_parser = history_subparsers.add_parser(
        'probe',
        help='探测历史数据 provider',
    )
    history_probe_parser.add_argument(
        '--symbol',
        type=str,
        default=DEFAULT_BACKTEST_SYMBOL,
    )
    history_probe_parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='历史起始日期，格式 YYYY-MM-DD',
    )
    history_probe_parser.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='历史结束日期，格式 YYYY-MM-DD',
    )
    history_probe_parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='数据 provider JSON 配置文件路径',
    )
    history_probe_parser.add_argument('--json', action='store_true', help='输出 JSON 格式')

    history_grid_parser = history_subparsers.add_parser(
        'export-grid',
        help='导出 grid 回测历史 CSV',
    )
    history_grid_parser.add_argument('--symbol', type=str, default=DEFAULT_BACKTEST_SYMBOL)
    history_grid_parser.add_argument('--start-date', type=str, help='历史起始日期，格式 YYYY-MM-DD')
    history_grid_parser.add_argument('--end-date', type=str, help='历史结束日期，格式 YYYY-MM-DD')
    history_grid_parser.add_argument('--input-json', type=str, help='本地历史 JSON 数组路径')
    history_grid_parser.add_argument('--config', type=str, help='数据 provider JSON 配置文件路径')
    history_grid_parser.add_argument('--output', type=str, required=True, help='输出 CSV 路径')

    history_rotation_parser = history_subparsers.add_parser(
        'export-rotation',
        help='导出 rotation 回测历史 CSV 长表',
    )
    history_rotation_parser.add_argument('--etf-pool', type=str, help='ETF池，逗号分隔')
    history_rotation_parser.add_argument('--start-date', type=str, help='历史起始日期，格式 YYYY-MM-DD')
    history_rotation_parser.add_argument('--end-date', type=str, help='历史结束日期，格式 YYYY-MM-DD')
    history_rotation_parser.add_argument('--lookback', type=int, help='prices 滚动窗口长度')
    history_rotation_parser.add_argument('--input-json', type=str, help='本地 symbol->history JSON 路径')
    history_rotation_parser.add_argument('--config', type=str, help='数据 provider JSON 配置文件路径')
    history_rotation_parser.add_argument('--output', type=str, required=True, help='输出 CSV 路径')

    backtest_parser = subparsers.add_parser('backtest', help='运行回测')
    backtest_parser.add_argument('--strategy', default='grid', choices=['grid', 'rotation'])
    backtest_parser.add_argument('--symbol', type=str, default=DEFAULT_BACKTEST_SYMBOL)
    backtest_parser.add_argument(
        '--history',
        type=str,
        help='历史行情文件；grid 使用 CSV，rotation 支持 CSV 长表或 JSON snapshot 数组',
    )
    backtest_parser.add_argument('--start-date', type=str, help='回测起始日期，格式 YYYY-MM-DD')
    backtest_parser.add_argument('--end-date', type=str, help='回测结束日期，格式 YYYY-MM-DD')
    backtest_parser.add_argument('--center-price', type=float)
    backtest_parser.add_argument('--grid-size', type=float)
    backtest_parser.add_argument('--grid-count', type=int)
    backtest_parser.add_argument('--shares-per-grid', type=int)
    backtest_parser.add_argument('--max-grids', type=int)
    backtest_parser.add_argument('--initial-capital', type=float)
    backtest_parser.add_argument('--commission-rate', type=float)
    backtest_parser.add_argument('--buy-commission-rate', type=float)
    backtest_parser.add_argument('--sell-commission-rate', type=float)
    backtest_parser.add_argument('--min-commission', type=float)
    backtest_parser.add_argument('--slippage-rate', type=float)
    backtest_parser.add_argument(
        '--max-volume-participation',
        type=float,
        help='单标的单根 bar 最大成交量参与率，范围 (0, 1]',
    )
    backtest_parser.add_argument(
        '--strict-trading-calendar',
        action='store_true',
        help='拒绝周末及通过 --holiday 指定的休市日',
    )
    backtest_parser.add_argument(
        '--holiday',
        action='append',
        help='额外休市日，格式 YYYY-MM-DD，可重复指定',
    )
    backtest_parser.add_argument(
        '--trading-day',
        action='append',
        help='显式交易日，格式 YYYY-MM-DD，可重复指定并覆盖周末或休市日',
    )
    backtest_parser.add_argument('--report-output', type=str, help='导出 Markdown 回测报告路径')
    backtest_parser.add_argument('--equity-output', type=str, help='导出权益曲线 CSV 路径')
    backtest_parser.add_argument('--portfolio-output', type=str, help='导出逐期组合快照 CSV 路径')
    backtest_parser.add_argument('--trades-output', type=str, help='导出成交明细 CSV 路径')
    backtest_parser.add_argument('--positions-output', type=str, help='导出逐期持仓明细 CSV 路径')
    backtest_parser.add_argument('--rejections-output', type=str, help='导出拒单明细 CSV 路径')
    backtest_parser.add_argument('--etf-pool', type=str, help='ETF池，逗号分隔')
    backtest_parser.add_argument('--lookback', type=int, help='轮动回看周期')
    backtest_parser.add_argument('--top-n', type=int, help='轮动选择ETF数量')
    backtest_parser.add_argument('--rebalance-days', type=int, help='轮动再平衡天数')

    args = parser.parse_args()

    if args.command == 'start':
        cmd_start(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'report':
        cmd_report(args)
    elif args.command == 'health':
        cmd_health(args)
    elif args.command == 'diagnose':
        try:
            cmd_diagnose(args)
        except (TypeError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == 'alerts':
        try:
            cmd_alerts(args)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.command == 'config':
        try:
            if args.config_command == 'validate':
                cmd_config_validate(args)
            elif args.config_command == 'show':
                cmd_config_show(args)
            elif args.config_command == 'init':
                cmd_config_init(args)
            else:
                config_parser.print_help()
        except (OSError, TypeError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == 'history':
        try:
            if args.history_command == 'probe':
                cmd_history_probe(args)
            elif args.history_command == 'export-grid':
                cmd_history_export_grid(args)
            elif args.history_command == 'export-rotation':
                cmd_history_export_rotation(args)
            else:
                history_parser.print_help()
        except (AdapterError, TypeError, ValueError) as exc:
            parser.error(str(exc))
    elif args.command == 'backtest':
        try:
            cmd_backtest(args)
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
