# 历史 provider 本地接入演练

本文提供一个不含凭据的本地演练流程，用于验证真实历史 provider 配置、凭据门禁、备源顺序、缓存统计和文本可观测性。

示例配置：

```powershell
examples\configs\history-providers.local.example.json
```

该配置声明：

- `tushare` 为第一优先 provider，需要环境变量 `TUSHARE_TOKEN`。
- `akshare` 为第二优先 provider，不需要 token，但需要本地安装可选依赖 `akshare` 后才可真实请求。
- `history_cache_ttl_seconds=3600`，用于避免本地反复请求上游。
- `mx_xuangu` / `mx_search` 仍保持 mock，避免把历史 provider 演练扩大到其他真实数据源。

## 只检查配置和凭据门禁

不访问真实网络，只验证配置可读、provider readiness 和缺失环境变量提示：

```powershell
python cli\commands.py health --config examples\configs\history-providers.local.example.json --no-state
```

未设置 `TUSHARE_TOKEN` 时，输出中应能看到：

```text
- mx_data history providers: tushare missing_env=TUSHARE_TOKEN; akshare ready
```

如果用于交付门禁，可运行：

```powershell
python cli\commands.py diagnose --config examples\configs\history-providers.local.example.json --strict --no-state
```

缺少 `TUSHARE_TOKEN` 时，`diagnose --strict` 会失败；这是预期行为，表示真实凭据未准备好。

## 启用真实 AKShare 演练

安装可选依赖：

```powershell
python -m pip install akshare
```

执行一次最小历史探测：

```powershell
python cli\commands.py history probe --config examples\configs\history-providers.local.example.json --symbol 510300 --start-date 2026-01-05 --end-date 2026-01-06
```

未设置 `TUSHARE_TOKEN` 时，运行时会跳过 `tushare` 并尝试 `akshare`。如果 AKShare 可用，文本输出应包含：

```text
历史 provider: last=akshare
历史 provider failures: tushare#1 REAL_HISTORY_PROVIDER_ENV_MISSING
```

真实上游可能因为依赖版本、网络、节假日数据或网页源变化失败。失败时不要放宽数据契约，应优先检查 provider stderr、缓存配置和上游可用性。

## 启用真实 TuShare 演练

TuShare 需要本地 token：

```powershell
$env:TUSHARE_TOKEN = '<本地 token>'
python cli\commands.py history probe --config examples\configs\history-providers.local.example.json --symbol 510300 --start-date 2026-01-05 --end-date 2026-01-06
Remove-Item Env:TUSHARE_TOKEN
```

不要把 token 写入 JSON、命令参数、日志或提交记录。`health` / `diagnose` 只展示变量名和缺失状态，不读取或展示变量值。

## 导出回测输入

provider 探测通过后，可以导出回测 CSV：

```powershell
python cli\commands.py history export-grid --config examples\configs\history-providers.local.example.json --symbol 510300 --start-date 2026-01-01 --end-date 2026-01-31 --output data\grid-history.csv
python cli\commands.py history export-rotation --config examples\configs\history-providers.local.example.json --etf-pool 510300,510500,159915 --start-date 2026-01-01 --end-date 2026-01-31 --lookback 3 --output data\rotation-history.csv
```

生成的真实行情 CSV 属于本地验收产物，默认不要提交到仓库。
