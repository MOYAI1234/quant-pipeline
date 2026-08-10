#!/usr/bin/env python3
"""用 tushare fund_daily 拉取 ETF 池完整 OHLCV 历史，输出 rotation 风格 CSV。

输出列: date,open,high,low,close,volume,amount
（volume=成交量手, amount=成交额千元, 单位与 fund_daily 一致；
 因子只用比率，单位一致即可。）

用法:
  python scripts/fetch_etf_ohlcv_tushare.py --output data/history/etf-pool-ohlcv.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ETF_POOL = {
    "159659": "159659.SZ",   # 中证1000增强
    "510300": "510300.SH",   # 沪深300
    "512400": "512400.SH",   # 有色金属
    "513010": "513010.SH",   # 恒生科技
    "515120": "515120.SH",   # 创新药
    "518880": "518880.SH",   # 黄金
}


def make_client():
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN")
    api_url = os.environ.get("TUSHARE_API_URL")
    if not token or not api_url:
        raise RuntimeError("需要 TUSHARE_TOKEN 与 TUSHARE_API_URL 环境变量")
    client = ts.pro_api(token)
    # 覆盖镜像 API 地址。tushare 无公开配置项, 只能写私有属性 _DataApi__http_url;
    # 依赖其 name-mangling 后的内部实现, tushare 大版本升级时需重新验证该字段是否仍有效。
    client._DataApi__http_url = api_url.rstrip("/") + "/"
    return client


def fetch_ohlcv(client, ts_code: str, start_date: str, end_date: str) -> list[dict]:
    """单次调用拉全量（镜像 API 一次返回区间内全部交易日，无需分页）。"""
    frame = client.fund_daily(
        ts_code=ts_code, start_date=start_date, end_date=end_date
    )
    if frame is None or frame.empty:
        return []
    return frame.to_dict("records")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tushare 拉取 ETF OHLCV")
    parser.add_argument("--output", required=True)
    parser.add_argument("--start-date", default="20240101")
    parser.add_argument("--end-date", default="")
    args = parser.parse_args(argv)

    end_date = args.end_date or date.today().isoformat().replace("-", "")
    client = make_client()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "symbol", "open", "high", "low", "close", "volume", "amount"],
        )
        writer.writeheader()
        failed = 0
        for short_code, ts_code in ETF_POOL.items():
            try:
                rows = fetch_ohlcv(client, ts_code, args.start_date, end_date)
            except Exception as exc:  # 网络/API异常不中断其他ETF
                print(f"{short_code} ({ts_code}): 拉取失败 - {exc}", file=sys.stderr)
                failed += 1
                continue
            rows.sort(key=lambda r: r["trade_date"])
            print(f"{short_code} ({ts_code}): {len(rows)} 天 "
                  f"{rows[0]['trade_date'] if rows else '-'} ~ "
                  f"{rows[-1]['trade_date'] if rows else '-'}")
            for r in rows:
                writer.writerow({
                    "date": r["trade_date"],
                    "symbol": short_code,
                    "open": r["open"],
                    "high": r["high"],
                    "low": r["low"],
                    "close": r["close"],
                    "volume": r["vol"],
                    "amount": r["amount"],
                })
        if failed:
            print(f"警告: {failed} 只 ETF 拉取失败", file=sys.stderr)
    print(f"已写入: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
