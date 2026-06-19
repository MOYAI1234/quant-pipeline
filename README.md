# quant-pipeline

ETF 量化助手 Pipeline，目标是把数据适配、策略生成、风控检查、模拟执行、监控报告和后续回测/实盘接口组织成一条可迭代的交易研究流水线。

## 当前阶段

当前代码处于 **mock 数据 + simulator 模拟交易** 阶段，适合用于验证策略状态机、执行器、风控链路和后续回测框架，不是生产实盘系统。

截至 2026-06-18，仓库已达到[研究/模拟验证版交付基线](docs/release-readiness.md)：完整离线验收为 `407 passed, 2 skipped`，并包含 provider 本地演练与确定性回测产物验收。该结论只说明工程链路可交付，不代表策略收益有效或具备实盘条件。

重要边界：

- 策略/因子研究是下一阶段核心，项目内回测只作为工程自验证和快速 sanity check；策略有效性需要通过聚宽、优矿、米筐等公开平台交叉验证后才能继续推进。
- `adapters/` 中的 `mx-data`、`mx-xuangu`、`mx-search`、`jason-kb` 适配器多数仍是占位实现；`mx-data` 仅先支持通过 `history_command` 接入外部命令式历史行情 provider。
- adapter 支持 `mode=mock|real`。默认 `mock` 会返回占位数据；未配置 provider 的 `real` 会明确标记为不可用并抛出 `ServiceUnavailableError`，避免把 0 或空列表误认为真实行情。
- `DataManager` 会校验实时行情、净值和历史行情的基础字段、数值类型和可选时效契约；字段缺失、返回 shape 错误或启用时效校验后的过期数据会抛出 `DataFetchError`，避免脏数据继续进入策略链路。
- `execution/Simulator` 是简化成交模型，支持整手、手续费、均价、持仓和市值估算；`OrderManager` 会记录 pipeline 内部订单的 pending/filled/failed/rejected 状态，但不包含真实券商撮合、滑点和报单回报同步。
- `monitor/AlertManager` 已支持结构化告警事件和可选 JSONL 文件输出，日报/周报会展示最近告警摘要；当前还未接飞书、邮件等外部通知通道。
- 回测输入：`backtest/BacktestRunner` 已支持最小 grid 历史样例、历史 bar list/CSV 和 OHLC 数据质量校验；`RotationBacktestRunner` 已支持内置多 ETF 轮动样例、外部 JSON snapshot 和 CSV 长表历史回测。
- 回测执行：两类 runner 均通过 `BacktestExecutionModel` 统一处理滑点、成交量参与率限制和拒单归因，再复用 `Simulator` 完成简化成交。
- 回测输出：两类 runner 均输出收益、最大回撤、最大回撤区间、交易次数、拒单次数与原因、胜率、总手续费及其占初始资金占比，并支持权益曲线/成交明细/持仓明细/拒单明细 CSV 导出。
- 回测配置：CLI 已支持可配置滑点、可选成交量参与率限制和可选严格交易日历。
- 回测限制：当前还不是完整回测系统，不含交易所官方日历、未成交余量结转和复杂组合；已支持成交量上限下的可选整手部分成交。真实历史数据源目前只提供外部命令 provider 接入位，仓库不内置 API key 或真实服务凭据。
- `persistence/JsonStateStore` 已支持保存和恢复 `Simulator`、`GridStrategy`、`RotationStrategy`、`OrderManager` 的 JSON 快照和运行 metadata，并提供旧版无顶层 `version` 状态到 v1 的最小迁移入口；`QuantPipeline` 默认会在启动时恢复、停止时保存到 `data/state.json`，但完整多版本迁移和 SQLite 存储仍未实现。
- QMT/实盘执行、API、Web、完整回测引擎仍未实现。

更多文档：

- [架构说明](docs/architecture.md)
- [测试与验收指南](docs/testing.md)
- [研究/模拟版交付状态](docs/release-readiness.md)
- [策略研究工作流](docs/strategy-research-workflow.md)
- [策略候选索引](docs/strategy-candidates/README.md)
- [策略候选模板](docs/strategy-candidate-template.md)
- [策略因子来源扫描](docs/strategy-factor-source-scan-2026-06-19.md)
- [聚宽复现脚本](examples/joinquant/README.md)
- [公开回测平台交叉验证](docs/public-backtest-validation.md)
- [PRD v3 差距审计与路线图](docs/prd-gap-audit-v3.md)
- [数据源 provider 选型矩阵](docs/data-source-provider-evaluation.md)
- [历史行情命令 provider 契约](docs/history-provider-contract.md)
- [历史 provider 本地接入演练](docs/provider-local-drill.md)
- [真实历史数据 guarded e2e 验收](docs/live-data-validation.md)

## 目录结构

```text
adapters/    外部数据和知识服务适配层
analysis/    宏观、ETF、新闻分析模块
cli/         命令行入口
config/      默认配置和日志配置
data/        数据管理、缓存和数据契约
execution/   模拟执行器和订单管理
monitor/     运行指标、告警和报告
persistence/ 账户和策略状态快照存储
risk/        ETF 质量、仓位和止损风控
strategy/    网格策略、轮动策略和策略管理器
tests/       单元测试和集成测试
```

## 本地运行

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

查看 CLI：

```powershell
python cli\commands.py --help
```

生成空组合日报：

```powershell
python cli\commands.py report --type daily
```

检查数据源健康状态：

```powershell
python cli\commands.py health
python cli\commands.py health --config path\to\config.json
python cli\commands.py health --json --strict
```

运行启动前诊断：

```powershell
python cli\commands.py diagnose
python cli\commands.py diagnose --json --strict
python cli\commands.py diagnose --state-path data\state.json
```

查看本地告警事件：

```powershell
python cli\commands.py alerts
python cli\commands.py alerts --json --limit 20
python cli\commands.py alerts --alert-file data\alerts.jsonl
```

初始化、查看和校验配置：

```powershell
python cli\commands.py config init
python cli\commands.py config show
python cli\commands.py config show --config config.local.json
python cli\commands.py config validate
python cli\commands.py config validate --json
python cli\commands.py config validate --config path\to\config.json
python cli\commands.py config validate --config path\to\config.json --strict-warnings
```

`config init` 默认生成被 `.gitignore` 忽略的 `config.local.json`，已有文件不会被覆盖；只有显式添加 `--force` 才会覆盖。真实 API key、token 和私有 provider 路径应只保存在本地配置或环境变量中。生产或 CI 场景可使用 `--strict-warnings` 将风险 warning 视为失败；`--json` 会额外输出 `strict_warnings`，便于自动化区分普通提示和阻断项。

运行内置样例回测：

```powershell
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy grid --start-date 2026-01-02 --end-date 2026-01-03
python cli\commands.py backtest --strategy grid --slippage-rate 0.001
python cli\commands.py backtest --strategy grid --max-volume-participation 0.05
python cli\commands.py backtest --strategy grid --max-volume-participation 0.05 --allow-partial-fills
python cli\commands.py backtest --strategy grid --buy-commission-rate 0.0002 --sell-commission-rate 0.0004 --min-commission 5
python cli\commands.py backtest --strategy grid --history path\to\history.csv --strict-trading-calendar
python cli\commands.py backtest --strategy grid --history path\to\history.csv --strict-trading-calendar --holiday 2026-01-02
python cli\commands.py backtest --strategy grid --report-output data\grid-report.md
python cli\commands.py backtest --strategy grid --equity-output data\grid-equity.csv
python cli\commands.py backtest --strategy grid --portfolio-output data\grid-portfolio.csv
python cli\commands.py backtest --strategy grid --trades-output data\grid-trades.csv
python cli\commands.py backtest --strategy grid --positions-output data\grid-positions.csv
python cli\commands.py backtest --strategy grid --rejections-output data\grid-rejections.csv
```

运行内置轮动样例回测：

```powershell
python cli\commands.py backtest --strategy rotation
python cli\commands.py backtest --strategy rotation --history path\to\rotation-history.json
python cli\commands.py backtest --strategy rotation --history path\to\rotation-history.csv
python cli\commands.py backtest --strategy rotation --report-output data\rotation-report.md
python cli\commands.py backtest --strategy rotation --equity-output data\rotation-equity.csv
python cli\commands.py backtest --strategy rotation --portfolio-output data\rotation-portfolio.csv
python cli\commands.py backtest --strategy rotation --trades-output data\rotation-trades.csv
python cli\commands.py backtest --strategy rotation --positions-output data\rotation-positions.csv
python cli\commands.py backtest --strategy rotation --rejections-output data\rotation-rejections.csv
```

一次生成并验证两种策略的完整交付产物；省略 `--output-dir` 时使用临时目录：

```powershell
python scripts\verify_backtest_artifacts.py --output-dir data\backtest-acceptance
```

rotation 历史 JSON 使用 snapshot 数组，单条结构如下：

```json
{
  "date": "2026-01-01",
  "symbols": {
    "510300": {"close": 12.0, "prices": [10.0, 11.0, 12.0], "volume": 1000000},
    "510500": {"close": 9.0, "prices": [10.0, 9.5, 9.0], "volume": 1000000}
  }
}
```

rotation 历史 CSV 使用长表，字段：`date,symbol,close,prices,volume`。其中 `prices` 使用 `|` 分隔，例如：

```csv
date,symbol,close,prices,volume
2026-01-01,510300,12.0,10|11|12,1000000
2026-01-01,510500,9.0,10|9.5|9,1000000
```

`--report-output` 会把 CLI 中展示的回测摘要写成 UTF-8 Markdown 文件，便于归档和评审。
`--commission-rate` 保留为买卖双边费率的兼容默认值；`buy_commission_rate` / `sell_commission_rate` 在配置中为 `null` 时继承该值，也可通过 `--buy-commission-rate`、`--sell-commission-rate` 分别覆盖。`--min-commission` 表示每笔成交的最低佣金。默认最低佣金为 0，以保持旧回测结果兼容；生产验收应按实际券商费率显式配置。
回测摘要还会输出总成交额、成交额占初始资金、每个历史周期的交易次数，以及已平仓交易对应手续费相对毛盈利的侵蚀比例。期末未平仓买单的手续费计入总手续费，但不混入已平仓手续费侵蚀比。这里的“成交额占初始资金”是用于比较策略交易强度的简化审计指标，不等同于基金或组合管理中的标准年化换手率。
grid 回测会按模拟器相同的 100 股整手规则，额外估算最近一档买卖网格完成一轮后的毛收益、手续费、滑点和净收益；不足一手、成本吞掉至少 50% 毛收益，或扣除成本后净收益不为正时，Markdown 报告会输出生产可行性警告。警告不会修改策略成交，只用于阻止把密集网格的毛收益误当成可落地收益。
权益曲线 CSV 字段：`date,total_value,pnl,pnl_percent,period_return,drawdown`。
组合快照 CSV 字段：`date,cash,position_count,positions_market_value,total_value,pnl,pnl_percent,realized_pnl,unrealized_pnl,total_value_delta`。其中 `total_value_delta` 用于校验 `cash + positions_market_value` 与 `total_value` 的差异。
成交明细 CSV 字段：`timestamp,action,symbol,price,shares,requested_shares,partial_fill,amount,commission,entry_commission,profit,net_profit`。
持仓明细 CSV 字段：`date,symbol,shares,avg_price,cost,commission,current_price,market_value,unrealized_pnl`。
拒单明细 CSV 字段：`timestamp,action,symbol,price,shares,amount,reason,signal_reason`。

使用 CSV 历史行情回测：

```powershell
python cli\commands.py backtest --strategy grid --history path\to\history.csv
```

验证 provider 并导出回测历史 CSV：

```powershell
python cli\commands.py history probe --config path\to\config.json --symbol 510300 --start-date 2026-01-05 --end-date 2026-01-06
python cli\commands.py history export-grid --input-json path\to\grid-history.json --output data\grid-history.csv
python cli\commands.py history export-rotation --input-json path\to\rotation-histories.json --lookback 3 --output data\rotation-history.csv
python cli\commands.py history export-grid --config path\to\config.json --symbol 510300 --start-date 2026-01-01 --end-date 2026-01-31 --output data\grid-history.csv
python cli\commands.py history export-rotation --config path\to\config.json --etf-pool 510300,510500,159915 --start-date 2026-01-01 --end-date 2026-01-31 --lookback 3 --symbol-delay-seconds 30 --output data\rotation-history.csv
```

本地评估首个 ETF 动量轮动候选策略的因子和过滤原因：

```powershell
python scripts\evaluate_etf_momentum_rotation.py --history data\rotation-history.csv --rebalance-step 5 --limit 12
```

本地回测首个 ETF 动量轮动候选策略的收益、换手、费用和过滤摘要：

```powershell
python scripts\backtest_etf_momentum_rotation.py --history data\rotation-history.csv --initial-capital 100000 --min-avg-amount 20000000 --min-commission 5 --slippage-rate 0.001
```

本地评估和回测 `ETF-DUAL-MOM-002` 月频双动量候选策略：

```powershell
python scripts\evaluate_etf_dual_momentum.py --history data\rotation-history.csv --risk-assets 510300,510500,159915,510880 --defensive-assets 518880 --lookback-days 120 --min-history-days 121 --limit 12
python scripts\backtest_etf_dual_momentum.py --history data\rotation-history.csv --risk-assets 510300,510500,159915,510880 --defensive-assets 518880 --lookback-days 120 --min-history-days 121 --initial-capital 100000 --min-amount 20000000 --min-commission 5 --slippage-rate 0.001
```

真实候选策略需要至少导出 `121` 左右的 `lookback`，才能覆盖 60 日动量、20 日确认、20 日波动和 120 日最小历史要求。
`ETF-DUAL-MOM-002` 标准 12 个月版本需要至少 `253` 左右的 `lookback`；若只导出 121 日窗口，只能做 120 日动量的临时 sanity check。

`--symbol-delay-seconds` 仅用于通过 provider 导出 rotation 历史，在相邻标的请求之间等待 0-60 秒。AKShare 等公开网页源出现连续请求限流时可显式启用；默认 0 保持原有行为。

`--input-json` 适合当前 mock/simulator 阶段导入本地历史数据；未提供 `--input-json` 时会通过 `DataManager.get_etf_history()` 拉取历史行情，当前 mock adapter 会返回空历史。真实历史行情 provider 需要通过 JSON 配置文件显式启用，例如：

```json
{
  "data": {
    "history_cache_ttl_seconds": 3600,
    "mx_data": {
      "mode": "real",
      "timeout": 10,
      "history_command": [
        "python",
        "scripts/fetch_history.py",
        "--symbol", "{symbol}",
        "--start-date", "{start_date}",
        "--end-date", "{end_date}"
      ]
    },
    "mx_xuangu": {"mode": "mock", "timeout": 10},
    "mx_search": {"mode": "mock", "timeout": 10}
  },
  "account": {
    "initial_capital": 100000,
    "commission_rate": 0.0003,
    "buy_commission_rate": 0.0003,
    "sell_commission_rate": 0.0003,
    "min_commission": 0
  },
  "risk": {"max_position": 5, "stop_loss": 0.15, "max_single_loss": 0.02, "min_volume": 10000000, "min_size": 1000000000, "max_tracking_error": 0.005, "max_premium": 0.05},
  "monitor": {"check_interval": 60, "alert_threshold": -10, "alert_file_path": null},
  "state": {"enabled": true, "path": "data/state.json", "restore_on_start": true, "save_on_stop": true}
}
```

`history_command` 必须输出 JSON 数组，或输出包含 `history` / `data` 数组字段的 JSON object；数组元素仍需满足 `date,open,high,low,close,volume,amount` 历史行情契约。

需要顺序降级时，可用 `history_providers` 替代单个 `history_command`：

```json
{
  "data": {
    "mx_data": {
      "mode": "real",
      "timeout": 10,
      "history_command": null,
      "history_providers": [
        {
          "name": "primary",
          "command": ["python", "primary.py", "{symbol}", "{start_date}", "{end_date}"],
          "required_env": ["PRIMARY_API_TOKEN"]
        },
        {
          "name": "backup",
          "command": ["python", "backup.py", "{symbol}", "{start_date}", "{end_date}"]
        }
      ],
      "history_retry_attempts": 2,
      "history_retry_delay_seconds": 0.5
    }
  }
}
```

每个命名 provider 可用 `required_env` 声明所需环境变量。`config validate` / `diagnose` 会在变量缺失时给出严格门禁 warning；运行时会跳过缺少凭据的 provider 并继续尝试备源。健康状态只输出变量名、缺失列表和 provider ready 状态，不读取或暴露变量值。

同一 provider 的进程启动失败、非零退出或超时会按 `history_retry_attempts` 重试，然后再切换到下一个 provider。缺少 `required_env` 属于配置可用性问题，不会反复重试同一来源；非法 UTF-8、非法 JSON 或错误输出结构也不会重复请求同一来源，但仍会尝试备源。重试次数范围为 1-10，等待时间范围为 0-60 秒；等待使用当前同步 pipeline 的阻塞式 sleep。`health --json` 和报告会展示当前进程的 provider ready 状态、最近成功来源、总尝试次数、结构化失败链、历史缓存 TTL、命中/未命中次数和最近一次历史缓存是否命中；文本 `health`、报告、`history probe` 和通过 provider 拉取的 `history export-*` 会额外输出简短失败链摘要，便于快速定位退化来源。`history probe --json` 以及通过 provider 拉取的 `history export-*` 会在执行历史请求的同一进程输出本次缓存统计和 provider 状态，便于发现“凭据缺失”“备源成功但主源已退化”“缓存窗口过长”或“缓存未命中导致频繁请求上游”的情况。历史结果缓存仍由 `DataManager` 负责，默认 `data.history_cache_ttl_seconds=3600`；如需调试 provider 可设为 `0` 禁用缓存，真实历史 provider 启用时 `config validate` 会对该配置给出上游请求压力警告，生产环境应避免过低 TTL。

`history probe` 会执行一次不落盘的最小查询，校验 provider 命令、JSON、历史字段、日期顺序和请求区间，并输出返回行数、实际首尾日期、本次历史缓存统计和 provider 状态。使用 `--json` 时，成功和失败都会输出 provider 状态；失败还会输出 `available=false`、错误码、来源和错误消息，便于 CI 或本地 provider 接入脚本判断失败原因。真实 API key、token 和私有 provider 脚本应保留在本地配置或环境变量中，不要提交到仓库。

仓库提供可选 AKShare 示例脚本 `examples/providers/akshare_history_provider.py`。它不会把 AKShare 加入项目依赖；需要本地自行 `pip install akshare` 后，再通过 `history_command` 调用。完整 provider 契约见 [docs/history-provider-contract.md](docs/history-provider-contract.md)。

仓库也提供可选 TuShare 示例脚本 `examples/providers/tushare_history_provider.py`。它使用未复权 `fund_daily` ETF 日线，将 `vol` 从手转换为股、`amount` 从千元转换为元，并从 `TUSHARE_TOKEN` 环境变量读取凭据。若使用 TuShare 反代，可设置 `TUSHARE_API_URL`，脚本会在创建 SDK client 后覆盖 `pro._DataApi__http_url`；token 和反代地址都不应写入仓库。建议通过命名 provider 配置：

```json
{
  "name": "tushare",
  "command": [
    "python",
    "examples/providers/tushare_history_provider.py",
    "--symbol", "{symbol}",
    "--start-date", "{start_date}",
    "--end-date", "{end_date}"
  ],
  "required_env": ["TUSHARE_TOKEN"]
}
```

TuShare 不会加入默认依赖，也不会在仓库内保存 token。其接口积分、频率、反代限速和服务条款由用户自己的 TuShare 账户或反代服务决定，不应把 guarded live test 通过解释为生产 SLA。若反代限速为每分钟 100 次，本地批量导出建议仍显式设置 1 秒左右的请求间隔；不要逐标的、逐日期高频循环请求。

如需验证真实 AKShare 或 TuShare 网络链路，可按 [docs/live-data-validation.md](docs/live-data-validation.md) 显式启用对应 guarded e2e。TuShare 反代可用 `python scripts\verify_tushare_proxy.py` 串起 live test、probe、真实 CSV 导出和回测加载；默认测试不会访问外部行情服务。

严格交易日历默认按周一至周五判断；`--holiday YYYY-MM-DD` 可重复指定额外休市日，`--trading-day YYYY-MM-DD` 可显式覆盖周末或休市日。未启用 `--strict-trading-calendar` 时保持原有行为，不额外拒绝历史日期。

`--max-volume-participation` 可选范围为 `(0, 1]`，限制同一根 bar 内单标的全部买入和卖出成交合计最多占该 bar 成交量的比例。默认情况下超限订单（含卖出订单）整笔按不成交处理；显式增加 `--allow-partial-fills` 后，回测会把超限订单裁成剩余成交量允许的 100 股整手数量，并在成交明细中记录原始申请股数和部分成交标记。GridStrategy 会按实际成交股数维护每格 ledger，RotationStrategy 不会把包含部分成交的调仓批次标记为完成。当前不会把未成交余量结转到下一根 bar。少于 100 股的非整手信号仍由模拟执行器拒绝，不归因于成交量上限。未配置参与率限制时保持原有无限流动性假设。

回测结果中的 `rejected_order_count`、`rejection_reasons` 和 `rejected_orders` 会区分成交量超限（`volume_limit`）与模拟执行器拒绝（`executor_rejected`）；拒单明细同时保留策略原始 `signal_reason`，便于判断零成交究竟来自无信号还是有信号但未成交。

grid 历史 CSV 字段：`date,open,high,low,close,volume,amount`。

启动网格策略模拟循环：

```powershell
python cli\commands.py start --strategy grid --symbol 510300
```

使用指定状态文件启动，或临时禁用状态持久化：

```powershell
python cli\commands.py start --strategy grid --state-path data\demo-state.json
python cli\commands.py start --strategy grid --no-state
```

状态文件相对路径会按项目根目录解析，避免从不同工作目录启动时写到意外位置。

如需把本地模拟告警写入文件，可在 `SYSTEM_CONFIG['monitor']` 中设置 `alert_file_path`，例如 `data/alerts.jsonl`。每行是一条结构化 JSON 告警事件。

如需在真实数据接入时启用行情时效门槛，可在 `SYSTEM_CONFIG['data']` 中设置 `max_realtime_age_seconds` 和 `max_nav_age_seconds`；默认值为 `None`，以兼容当前 mock 空时间戳。未来时间戳容忍窗口由 `max_timestamp_future_skew_seconds` 控制，默认 60 秒。不带时区的行情 timestamp 会按 `timestamp_timezone_offset` 解释，默认 `+08:00`。

注意：当前默认数据适配器返回 mock/空数据，`start` 命令主要用于验证程序链路，不代表真实行情运行。

## 测试

运行研究/模拟版离线验收：

```powershell
python scripts\verify_offline.py
```

运行全部测试：

```powershell
python -m pytest -q
```

基础语法检查：

```powershell
python -m compileall -q .
```

当前测试重点覆盖：

- adapter 的 mock/real 模式、结构化健康检查、未实现 real 操作错误，以及命令式历史 provider 的凭据门禁、重试和顺序降级
- CLI `health` 对数据源健康状态的文本/JSON 输出
- CLI `diagnose` 对配置、风险 warning、数据源、缓存策略和状态文件的启动前诊断，并输出结构化阻断原因
- CLI `report` / `ReportGenerator` 对数据源健康状态、缓存策略和告警事件的报告输出
- CLI `alerts` 对本地 JSONL 告警事件的文本/JSON 输出、limit 和错误处理
- CLI `config validate` 对内置配置和 JSON 配置文件的校验，包括真实历史 provider 禁用缓存时的频率风险 warning、`--strict-warnings` 风险门禁和 JSON `strict_warnings` 输出
- CLI `config show/init` 对有效配置查看和本地模板安全生成
- `DataManager` 对实时行情、净值和历史行情的字段、数值类型、非负单位、可选时效契约校验、可配置历史缓存 TTL 和健康输出
- `DataManager` 缓存过期重取和 adapter 异常包装
- `RiskManager` 买入仓位上限、已有标的加仓、单笔权重、无持仓卖出、固定止损、单笔止损、跟踪止损和组合亏损告警
- `Simulator` 买入、卖出、均价、部分卖出和市值估算
- `BacktestExecutionModel` 的滑点、成交量参与率限制和同一 bar 内成交量占用
- `BacktestRunner` 的 grid 买卖周期、日期区间过滤、历史日期/盘中时间顺序与 OHLC 合法性校验、最大回撤区间、胜率/手续费统计、滑点执行价、权益曲线/组合快照/成交明细 CSV 导出、轮动样例回测、空历史保护、CSV 读取/错误处理和 CLI smoke
- `history export-grid/export-rotation` 对 DataManager 历史数据、外部历史 provider 配置和本地 JSON 到回测 CSV 的转换
- `history probe` 对真实历史 provider 的最小查询、数据契约校验和 JSON 失败输出
- AKShare / TuShare 示例 provider 的字段、日期、代码和成交量/成交额单位转换
- `GridStrategy` 多格买入、同格防重复、卖出、止损后 ledger 重置
- `RotationStrategy` 首次调仓、卖旧买新、失败 pending 清理和重试
- `JsonStateStore` 对账户、网格 ledger、轮动调仓状态、成交快照、订单状态、运行 metadata 和旧版状态迁移的保存/恢复
- `QuantPipeline.run_once()` 单轮策略执行、订单状态流转、监控更新，以及启动/停止状态恢复保存
- 日报/周报中输出数据源健康状态和告警事件摘要
- `AlertManager` 结构化事件、JSONL 输出、亏损/持仓告警触发和历史记录裁剪

更多测试分层和验收口径见 [docs/testing.md](docs/testing.md)。

## 下一步路线

研究/模拟验证版已经收口，后续研发重心转向策略/因子研究闭环：

1. 按[策略研究工作流](docs/strategy-research-workflow.md)维护[策略候选索引](docs/strategy-candidates/README.md)，让每个策略想法都有来源、因子、成本、风险和验证计划。
2. 当前首个候选是 [ETF 动量质量轮动 v1](docs/strategy-candidates/etf-momentum-rotation-v1.md)，状态为 `researching`，尚未通过公开平台验证。
3. 先在聚宽运行 [ETF 动量质量轮动 v1 复现脚本](examples/joinquant/etf_momentum_rotation_v1.py)，再按[公开回测平台交叉验证](docs/public-backtest-validation.md)归档平台参数和结果。
4. 使用项目内真实 provider 和 backtest 做工程 sanity check，重点验证数据契约、费用、滑点、成交量参与率、止损和风控是否会推翻策略。
5. 只有公开平台验证通过、差异可解释、保守成本下结论不反转，才进入模拟盘或小资金实盘预研，并另行补齐真实订单状态机、kill switch 和运行审计。

实盘相关能力必须在显式配置、充分测试和状态可恢复后再启用。
