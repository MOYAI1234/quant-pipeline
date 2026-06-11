# 历史行情命令 provider 契约

本文定义 data.mx_data.history_command 的命令行契约。该能力用于把仓库外部的数据源脚本接入 DataManager.get_etf_history()、history probe 和 history export-*，不代表仓库内置真实行情服务。

## 调用方式

配置文件中 data.mx_data.mode 必须为 real，并提供 history_command 字符串数组。数组元素可使用以下占位符：

- {symbol}：ETF 代码，例如 510300
- {start_date}：开始日期，格式 YYYY-MM-DD
- {end_date}：结束日期，格式 YYYY-MM-DD

示例：

~~~json
{
  "data": {
    "mx_data": {
      "mode": "real",
      "timeout": 30,
      "history_command": [
        "python",
        "examples/providers/akshare_history_provider.py",
        "--symbol", "{symbol}",
        "--start-date", "{start_date}",
        "--end-date", "{end_date}"
      ]
    }
  }
}
~~~

## stdout 契约

provider 必须向 stdout 输出 UTF-8 JSON，且必须是以下二者之一：

~~~json
[
  {
    "date": "2026-01-01",
    "open": 4.0,
    "high": 4.2,
    "low": 3.9,
    "close": 4.1,
    "volume": 1000,
    "amount": 4100.0
  }
]
~~~

或：

~~~json
{
  "history": [
    {
      "date": "2026-01-01",
      "open": 4.0,
      "high": 4.2,
      "low": 3.9,
      "close": 4.1,
      "volume": 1000,
      "amount": 4100.0
    }
  ]
}
~~~

对象格式也可使用 data 字段代替 history。其他 metadata 会被 MXDataAdapter 忽略。

## 字段要求

每条历史行情必须包含：

| 字段 | 类型 | 要求 |
|---|---|---|
| date | string | YYYY-MM-DD；必须落在请求区间内 |
| open | number | 有限正数 |
| high | number | 有限正数，且满足 OHLC 合法性 |
| low | number | 有限正数，且满足 OHLC 合法性 |
| close | number | 有限正数 |
| volume | integer | 非负整数 |
| amount | number | 有限非负数 |

返回顺序必须按日期严格递增。history probe 会校验空数据、字段缺失、非法数值、日期乱序和请求区间外数据。

## 错误契约

- 成功：退出码 0，stdout 是合法 JSON。
- 失败：退出码非 0，stderr 写清楚原因；stdout 不应混入日志。
- 超时：由 data.mx_data.timeout 控制，超时会被视为 provider 不可用。

不要把 API key、token、cookie、私有路径或完整真实行情缓存提交到仓库。需要凭据的数据源必须只通过本地配置或环境变量启用。

## AKShare 示例

仓库提供一个可选示例脚本：

~~~powershell
python examples\providers\akshare_history_provider.py --symbol 510300 --start-date 2026-01-01 --end-date 2026-01-31
~~~

该脚本不会随项目依赖自动安装 AKShare。使用前请在本地环境自行安装：

~~~powershell
pip install akshare
~~~

脚本使用 AKShare 的 fund_etf_hist_em 日级 ETF 历史行情接口，将 AKShare 的中文字段转换为本项目历史行情契约字段。它适合作为本地 POC 和 history probe 验收入口，不应绕过 DataManager 的契约校验。
