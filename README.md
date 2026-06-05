# quant-pipeline

ETF 量化助手 Pipeline，目标是把数据适配、策略生成、风控检查、模拟执行、监控报告和后续回测/实盘接口组织成一条可迭代的交易研究流水线。

## 当前阶段

当前代码处于 **mock 数据 + simulator 模拟交易** 阶段，适合用于验证策略状态机、执行器、风控链路和后续回测框架，不是生产实盘系统。

重要边界：

- `adapters/` 中的 `mx-data`、`mx-xuangu`、`mx-search`、`jason-kb` 适配器目前仍是占位实现，未接真实外部服务。
- adapter 支持 `mode=mock|real`。默认 `mock` 会返回占位数据；`real` 当前会明确标记为不可用并抛出 `ServiceUnavailableError`，避免把 0 或空列表误认为真实行情。
- `DataManager` 会校验实时行情、净值和历史行情的基础字段、数值类型和可选时效契约；字段缺失、返回 shape 错误或启用时效校验后的过期数据会抛出 `DataFetchError`，避免脏数据继续进入策略链路。
- `execution/Simulator` 是简化成交模型，支持整手、手续费、均价、持仓和市值估算；`OrderManager` 会记录 pipeline 内部订单的 pending/filled/failed/rejected 状态，但不包含真实券商撮合、滑点和报单回报同步。
- `monitor/AlertManager` 已支持结构化告警事件和可选 JSONL 文件输出，日报/周报会展示最近告警摘要；当前还未接飞书、邮件等外部通知通道。
- `backtest/BacktestRunner` 已支持最小 grid 历史样例回测，`RotationBacktestRunner` 已支持内置多 ETF 轮动样例回测，并复用 `Simulator` 输出收益、最大回撤、交易次数、胜率和可配置滑点等基础指标；当前还不是完整回测系统，不含交易日历、复杂组合和真实历史数据源。
- `persistence/JsonStateStore` 已支持保存和恢复 `Simulator`、`GridStrategy`、`RotationStrategy`、`OrderManager` 的 JSON 快照和运行 metadata，并提供旧版无顶层 `version` 状态到 v1 的最小迁移入口；`QuantPipeline` 默认会在启动时恢复、停止时保存到 `data/state.json`，但完整多版本迁移和 SQLite 存储仍未实现。
- QMT/实盘执行、API、Web、完整回测引擎仍未实现。

更多差距和路线图见 [docs/prd-gap-audit-v3.md](docs/prd-gap-audit-v3.md)。

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
python cli\commands.py health --json --strict
```

查看本地告警事件：

```powershell
python cli\commands.py alerts
python cli\commands.py alerts --json --limit 20
python cli\commands.py alerts --alert-file data\alerts.jsonl
```

校验配置：

```powershell
python cli\commands.py config validate
python cli\commands.py config validate --json
python cli\commands.py config validate --config path\to\config.json
```

运行内置样例回测：

```powershell
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy grid --start-date 2026-01-02 --end-date 2026-01-03
python cli\commands.py backtest --strategy grid --slippage-rate 0.001
```

运行内置轮动样例回测：

```powershell
python cli\commands.py backtest --strategy rotation
```

使用 CSV 历史行情回测：

```powershell
python cli\commands.py backtest --strategy grid --history path\to\history.csv
```

CSV 字段：`date,open,high,low,close,volume,amount`。

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

运行全部测试：

```powershell
python -m pytest -q
```

基础语法检查：

```powershell
python -m compileall -q .
```

当前测试重点覆盖：

- adapter 的 mock/real 模式、结构化健康检查和未实现 real 模式错误
- CLI `health` 对数据源健康状态的文本/JSON 输出
- CLI `alerts` 对本地 JSONL 告警事件的文本/JSON 输出、limit 和错误处理
- CLI `config validate` 对内置配置和 JSON 配置文件的校验
- `DataManager` 对实时行情、净值和历史行情的字段、数值类型、非负单位和可选时效契约校验
- `DataManager` 缓存过期重取和 adapter 异常包装
- `RiskManager` 买入仓位上限、已有标的加仓、单笔权重、无持仓卖出、固定止损、单笔止损、跟踪止损和组合亏损告警
- `Simulator` 买入、卖出、均价、部分卖出和市值估算
- `BacktestRunner` 的 grid 买卖周期、日期区间过滤、历史日期/盘中时间顺序校验、胜率统计、滑点执行价、轮动样例回测、空历史保护、CSV 读取/错误处理和 CLI smoke
- `GridStrategy` 多格买入、同格防重复、卖出、止损后 ledger 重置
- `RotationStrategy` 首次调仓、卖旧买新、失败 pending 清理和重试
- `JsonStateStore` 对账户、网格 ledger、轮动调仓状态、成交快照、订单状态、运行 metadata 和旧版状态迁移的保存/恢复
- `QuantPipeline.run_once()` 单轮策略执行、订单状态流转、监控更新，以及启动/停止状态恢复保存
- 日报/周报中输出数据源健康状态和告警事件摘要
- `AlertManager` 结构化事件、JSONL 输出、亏损/持仓告警触发和历史记录裁剪

## 下一步路线

优先级从高到低：

1. 补强测试和主循环可测性。
2. 明确 adapter 的 mock/real 模式和数据契约。
3. 扩展历史行情驱动的回测引擎。
4. 持久化账户、成交和策略状态。
5. 完善监控报告和告警闭环。
6. 在模拟和回测稳定后，再预研 QMT/实盘执行。

实盘相关能力必须在显式配置、充分测试和状态可恢复后再启用。
