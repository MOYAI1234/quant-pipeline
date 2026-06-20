import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.history_adapter import (
    build_rotation_history_intersection,
    write_rotation_history_csv,
)
from data.data_manager import DataManager


def main() -> int:
    parser = argparse.ArgumentParser(
        description='导出按共同交易日对齐的轮动研究 CSV',
    )
    parser.add_argument('--input-json', help='本地 symbol->history JSON 路径')
    parser.add_argument('--config', help='真实历史 provider 配置 JSON 路径')
    parser.add_argument('--etf-pool', help='逗号分隔 ETF 池；provider 模式必填')
    parser.add_argument('--start-date', help='历史起始日期，格式 YYYY-MM-DD')
    parser.add_argument('--end-date', help='历史结束日期，格式 YYYY-MM-DD')
    parser.add_argument('--lookback', type=int, required=True, help='prices 滚动窗口长度')
    parser.add_argument(
        '--symbol-delay-seconds',
        type=float,
        default=0,
        help='多标的 provider 请求间隔秒数，默认 0',
    )
    parser.add_argument('--output', required=True, help='输出 CSV 路径')
    args = parser.parse_args()

    try:
        histories = _load_histories(args)
        history = build_rotation_history_intersection(
            histories,
            lookback=args.lookback,
        )
        output_path = write_rotation_history_csv(args.output, history)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f'已导出交集轮动历史: {output_path}, '
        f'snapshots={len(history)}, symbols={len(history[0]["symbols"]) if history else 0}'
    )
    return 0


def _load_histories(args) -> dict:
    if args.input_json and args.config:
        raise ValueError('--input-json 和 --config 不能同时使用')
    if args.input_json:
        return _load_input_json(args.input_json)
    if not args.config:
        raise ValueError('必须提供 --input-json 或 --config')
    return _fetch_provider_histories(args)


def _load_input_json(path: str) -> dict:
    with Path(path).open(encoding='utf-8') as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError('input JSON 顶层必须是 symbol->history 对象')
    return data


def _fetch_provider_histories(args) -> dict:
    if not args.start_date or not args.end_date:
        raise ValueError('provider 模式必须提供 --start-date 和 --end-date')
    symbols = _parse_symbols(args.etf_pool)
    data_config = _load_data_config(args.config)
    manager = DataManager(data_config)
    histories = {}
    try:
        manager.connect()
        for index, symbol in enumerate(symbols):
            histories[symbol] = manager.get_etf_history(
                symbol,
                args.start_date,
                args.end_date,
            )
            if args.symbol_delay_seconds and index < len(symbols) - 1:
                time.sleep(args.symbol_delay_seconds)
    finally:
        manager.disconnect()
    return histories


def _load_data_config(path: str) -> dict:
    with Path(path).open(encoding='utf-8') as file:
        config = json.load(file)
    if not isinstance(config, dict) or not isinstance(config.get('data'), dict):
        raise ValueError('配置文件缺少 data 对象')
    return config['data']


def _parse_symbols(value: str | None) -> list[str]:
    symbols = [
        symbol.strip()
        for symbol in (value or '').split(',')
        if symbol.strip()
    ]
    if not symbols:
        raise ValueError('--etf-pool 不能为空')
    return symbols


if __name__ == '__main__':
    raise SystemExit(main())
