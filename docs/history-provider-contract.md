# 历史行情命令 provider 契约

本文定义 data.mx_data.history_command 的命令行契约。该能力用于把仓库外部的数据源脚本接入 DataManager.get_etf_history()、history probe 和 history export-*，不代表仓库内置真实行情服务。

## 调用方式

配置文件中 `data.mx_data.mode` 必须为 `real`，并提供以下二者之一：

- `history_command`：单个命令的字符串数组，保持向后兼容。
- `history_providers`：按优先级排列的命名 provider 数组，每项包含 `name` 和 `command`。
- `history_providers[].required_env`：可选的非空环境变量名数组，用于声明 provider 所需凭据，不保存凭据值。

两者不能同时配置。命令数组元素可使用以下占位符：

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

多 provider 示例：

~~~json
{
  "data": {
    "mx_data": {
      "mode": "real",
      "timeout": 30,
      "history_providers": [
        {
          "name": "primary",
          "command": [
            "python",
            "scripts/primary_history.py",
            "--symbol", "{symbol}",
            "--start-date", "{start_date}",
            "--end-date", "{end_date}"
          ],
          "required_env": ["PRIMARY_API_TOKEN"]
        },
        {
          "name": "backup",
          "command": [
            "python",
            "scripts/backup_history.py",
            "--symbol", "{symbol}",
            "--start-date", "{start_date}",
            "--end-date", "{end_date}"
          ]
        }
      ],
      "history_retry_attempts": 2,
      "history_retry_delay_seconds": 0.5
    }
  }
}
~~~

`history_retry_attempts` 是每个 provider 的总尝试次数，范围为 1-10；默认 1。`history_retry_delay_seconds` 是可用性错误重试前的等待秒数，范围为 0-60；默认 0。当前 pipeline 使用同步阻塞式等待，未来异步执行层需要替换该等待实现。

`required_env` 只声明环境变量名称。配置校验和启动诊断会检查变量是否存在，健康状态会输出 `ready` 与 `missing_env`，但不会读取或展示变量值。运行时缺少凭据的 provider 会被记录为失败并跳过，不会重复请求同一来源；如果后续备源可用，仍会继续降级。

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
| volume | integer | 非负整数，单位为股 |
| amount | number | 有限非负数 |

返回顺序必须按日期严格递增。history probe 会校验空数据、字段缺失、非法数值、日期乱序和请求区间外数据。

## 错误契约

- 成功：退出码 0，stdout 是合法 JSON。
- 失败：退出码非 0，stderr 写清楚原因；stdout 不应混入日志。
- 超时：由 data.mx_data.timeout 控制，超时会被视为 provider 不可用。

进程启动失败、非零退出和超时属于可用性错误，会在当前 provider 内重试，再按配置顺序切换备源。多 provider 模式不会因为某个 executable 在启动前不可解析而阻断整个链路。非法 UTF-8、非法 JSON 或错误 JSON shape 属于确定性响应错误，不重试同一 provider，但会继续尝试下一个 provider。

所有 provider 都失败时，异常会包含 provider 名称、尝试序号和失败原因。`MXDataAdapter.health_check()` 还会输出：

- `last_history_provider`：最近一次成功 provider。
- `last_history_attempts`：最近一次请求执行的命令总次数。
- `last_history_failures`：最近一次请求的结构化失败链。
- `last_history_error`：同一失败链的文本摘要。

健康检查本身只报告配置和最近运行状态，不主动访问真实行情服务。

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

脚本使用 AKShare 的 fund_etf_hist_em 日级 ETF 历史行情接口，将 AKShare 的中文字段转换为本项目历史行情契约字段。AKShare / Eastmoney 的成交量字段按“手”返回，脚本会先转换为“股”再输出 volume，避免回测成交量参与率限制低估真实可成交量。它适合作为本地 POC 和 history probe 验收入口，不应绕过 DataManager 的契约校验。
