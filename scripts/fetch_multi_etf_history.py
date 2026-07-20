#!/usr/bin/env python3
"""拉取多 ETF 的日线历史数据并导出为 rotation CSV，供回测引擎使用。

用法:
  python scripts/fetch_multi_etf_history.py --start 2025-07-09 --end 2026-07-09
  python scripts/fetch_multi_etf_history.py --etfs 510300,510500,159915 --start 2025-01-01 --end 2026-07-09
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

import requests


MX_API_BASE = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"

DEFAULT_ETF_POOL = [
    "510300",  # 沪深300ETF
    "510500",  # 中证500ETF
    "159915",  # 创业板ETF
    "512100",  # 中证1000ETF
    "512880",  # 证券ETF
    "159920",  # 恒生ETF
    "513100",  # 纳指ETF
    "588000",  # 科创50ETF
    "516160",  # 新能源ETF
    "159865",  # 养殖ETF
]


def get_api_key():
    key = os.getenv("MX_APIKEY")
    if not key:
        raise ValueError("请设置环境变量 MX_APIKEY")
    return key


def _parse_numeric(value, default=0.0):
    """解析带单位的数值，如 '4.916元' -> 4.916, '9.559亿股' -> 955900000, '46.36亿' -> 4636000000"""
    if value is None or value == "" or value == "-":
        return default
    s = str(value).strip()
    # 移除常见后缀
    for suffix in ["元", "点", "%", "股"]:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    # 处理亿/万单位
    multiplier = 1.0
    if "亿" in s:
        multiplier = 100000000
        s = s.replace("亿", "")
    elif "万" in s:
        multiplier = 10000
        s = s.replace("万", "")
    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        return default


def _clean_date(dt):
    """清洗日期: '2026-07-09(日)' -> '2026-07-09'"""
    s = str(dt).strip()
    # 去掉括号及之后的内容
    idx = s.find("(")
    if idx > 0:
        s = s[:idx]
    return s[:10]


def fetch_etf_history(api_key: str, symbol: str, start_date: str, end_date: str) -> list[dict]:
    """调用妙想 API 拉取 ETF 日线历史。"""
    query = f"{symbol} {start_date}到{end_date}每个交易日开盘价收盘价最高价最低价成交量成交额"
    
    headers = {
        "Content-Type": "application/json",
        "apikey": api_key,
    }
    payload = {
        "toolQuery": query,
    }
    
    resp = requests.post(MX_API_BASE, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    status_code = data.get("status")
    if status_code != 0:
        error_msg = data.get("message", "unknown error")
        raise RuntimeError(f"API 返回错误 (status={status_code}): {error_msg}")
    
    # 导航: data.data.searchDataResultDTO.dataTableDTOList
    outer_data = data.get("data", {})
    inner_data = outer_data.get("data", {})
    search_result = inner_data.get("searchDataResultDTO", {})
    blocks = search_result.get("dataTableDTOList", [])
    
    if not blocks:
        blocks = outer_data.get("dataTableDTOList", [])
    
    # Block 0 = 实时行情 (1行), Block 1 = 历史行情 (多行)
    # 找到有历史数据的 block (headName 长度 > 1)
    history_block = None
    for block in blocks:
        table = block.get("table") or {}
        hn = table.get("headName", [])
        if len(hn) > 1:
            history_block = block
            break
    
    if history_block is None:
        # 回退: 用最后一个有数据的block
        for block in reversed(blocks):
            table = block.get("table") or {}
            if len(table.get("headName", [])) > 1:
                history_block = block
                break
    
    if history_block is None:
        return []
    
    table = history_block.get("table") or {}
    head_name = table.get("headName", [])
    name_map = history_block.get("nameMap", {})
    
    # 建立 field -> key 映射
    field_keys = {}
    for key, label in name_map.items():
        if key == "headNameSub":
            continue
        label_str = str(label)
        if "开盘" in label_str:
            field_keys["open"] = key
        elif "最高" in label_str:
            field_keys["high"] = key
        elif "最低" in label_str:
            field_keys["low"] = key
        elif "收盘" in label_str:
            field_keys["close"] = key
        elif "成交" in label_str and "量" in label_str:
            field_keys["volume"] = key
        elif "成交" in label_str and "额" in label_str:
            field_keys["amount"] = key
    
    records = []
    for i, dt in enumerate(head_name):
        date_str = _clean_date(dt)
        if not date_str:
            continue
        
        record = {"date": date_str}
        for field, key in field_keys.items():
            values = table.get(key, table.get(str(key), []))
            val = values[i] if i < len(values) else None
            record[field] = _parse_numeric(val)
        
        # 只保留有收盘价的记录
        if record.get("close", 0) > 0:
            records.append(record)
    
    # 数据是倒序的 (最新在前)，反转成时间升序
    records.sort(key=lambda r: r["date"])
    return records


def build_rotation_history(histories: dict[str, list[dict]], lookback: int = 120) -> list[dict]:
    """将多个 ETF 的历史数据合并为 rotation CSV 格式的快照列表。"""
    # 按日期合并
    date_map = {}
    for symbol, records in histories.items():
        for r in records:
            d = r["date"]
            if d not in date_map:
                date_map[d] = {}
            date_map[d][symbol] = r
    
    # 按日期排序并过滤掉数据不完整的日期
    snapshots = []
    symbols = list(histories.keys())
    for d in sorted(date_map):
        day_data = date_map[d]
        if not all(s in day_data for s in symbols):
            continue
        
        symbols_data = {}
        for s in symbols:
            bar = day_data[s]
            prices_str = _build_prices_string(histories[s], d, lookback)
            symbols_data[s] = {
                "close": bar.get("close", 0),
                "prices": prices_str,
                "volume": bar.get("volume", 0),
                "amount": bar.get("amount", 0),
            }
        
        snapshots.append({"date": d, "symbols": symbols_data})
    
    return snapshots


def _build_prices_string(records: list[dict], target_date: str, lookback: int) -> str:
    """为指定日期构建价格历史字符串（用 | 分隔）。"""
    # 找到 target_date 及之前的所有 close 价格
    closes = []
    for r in records:
        if r["date"] <= target_date:
            closes.append(r.get("close", 0))
    
    # 取最近的 lookback 个
    if len(closes) > lookback:
        closes = closes[-lookback:]
    
    return "|".join(str(c) for c in closes if c > 0)


def write_rotation_csv(snapshots: list[dict], output_path: str):
    """将快照列表写入 rotation CSV。"""
    if not snapshots:
        print("没有数据可写", file=sys.stderr)
        return
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "symbol", "close", "prices", "volume", "amount"])
        
        for snap in snapshots:
            d = snap["date"]
            for symbol, bar in snap["symbols"].items():
                writer.writerow([
                    d,
                    symbol,
                    bar.get("close", 0),
                    bar.get("prices", ""),
                    bar.get("volume", 0),
                    bar.get("amount", 0),
                ])
    
    print(f"Rotation CSV 已写入: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="拉取 ETF 日线历史并导出 rotation CSV")
    parser.add_argument("--etfs", default="", help="逗号分隔的 ETF 代码列表")
    parser.add_argument("--start", default="2025-07-09", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="2026-07-09", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--output", default="data/history/multi_etf_rotation.csv", help="输出路径")
    parser.add_argument("--lookback", type=int, default=120, help="价格历史回看天数")
    args = parser.parse_args()
    
    etf_pool = (
        [s.strip() for s in args.etfs.split(",") if s.strip()]
        if args.etfs else DEFAULT_ETF_POOL
    )
    
    api_key = get_api_key()
    histories = {}
    
    for i, symbol in enumerate(etf_pool):
        print(f"[{i+1}/{len(etf_pool)}] 拉取 {symbol} 历史数据 {args.start} ~ {args.end} ...")
        try:
            records = fetch_etf_history(api_key, symbol, args.start, args.end)
            print(f"  -> 获取 {len(records)} 条记录")
            histories[symbol] = records
        except Exception as e:
            print(f"  -> 拉取失败: {e}", file=sys.stderr)
        
        # 避免请求过快
        if i < len(etf_pool) - 1:
            time.sleep(1)
    
    if not histories:
        print("未获取到任何数据", file=sys.stderr)
        sys.exit(1)
    
    print(f"\n构建 rotation 历史 (lookback={args.lookback}) ...")
    snapshots = build_rotation_history(histories, lookback=args.lookback)
    print(f"生成 {len(snapshots)} 个交易日的快照")
    
    output_path = args.output
    if not Path(output_path).is_absolute():
        output_path = str(Path(__file__).resolve().parents[1] / output_path)
    write_rotation_csv(snapshots, output_path)
    
    # 同时输出日期范围
    if snapshots:
        print(f"日期范围: {snapshots[0]['date']} ~ {snapshots[-1]['date']}")
        print(f"ETF 池: {', '.join(histories.keys())}")


if __name__ == "__main__":
    main()
