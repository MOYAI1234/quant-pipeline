# quant-pipeline

ETF 量化助手 Pipeline，目标是把数据适配、策略生成、风控检查、模拟执行、监控报告和后续回测/实盘接口组织成一条可迭代的交易研究流水线。

## 当前阶段

当前代码处于 **mock 数据 + simulator 模拟交易** 阶段，适合用于验证策略状态机、执行器、风控链路和后续回测框架，不是生产实盘系统。

重要边界：

- `adapters/` 中的 `mx-data`、`mx-xuangu`、`mx-search`、`jason-kb` 适配器目前仍是占位实现，未接真实外部服务。
- adapter 支持 `mode=mock|real`。默认 `mock` 会返回占位数据；`real` 当前会明确标记为不可用并抛出 `ServiceUnavailableError`，避免把 0 或空列表误认为真实行情。
- `DataManager` 会校验实时行情、净值和历史行情的基础字段契约；字段缺失或返回 shape 错误会抛出 `DataFetchError`，避免脏数据继续进入策略链路。
- `execution/Simulator` 是简化成交模型，支持整手、手续费、均价、持仓和市值估算；`OrderManager` 会记录 pipeline 内部订单的 pending/filled/failed/rejected 状态，但不包含真实券商撮合、滑点和报单回报同步。
- `backtest/BacktestRunner` 已支持最小 grid 历史样例回测，`RotationBacktestRunner` 已支持内置多 ETF 轮动样例回测，并复用 `Simulator`；当前还不是完整回测系统，不含交易日历、滑点、复杂组合和真实历史数据源。
- `persistence/JsonStateStore` 已支持保存和恢复 `Simulator`、`GridStrategy`、`RotationStrategy`、`OrderManager` 的 JSON 快照和运行 metadata；`QuantPipeline` 默认会在启动时恢复、停止时保存到 `data/state.json`，但状态迁移策略仍未实现。
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

运行内置样例回测：

```powershell
python cli\commands.py backtest --strategy grid
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
- `DataManager` 对实时行情、净值和历史行情的字段契约校验
- `Simulator` 买入、卖出、均价、部分卖出和市值估算
- `BacktestRunner` 的 grid 买卖周期、轮动样例回测、空历史保护、CSV 读取/错误处理和 CLI smoke
- `GridStrategy` 多格买入、同格防重复、卖出、止损后 ledger 重置
- `RotationStrategy` 首次调仓、卖旧买新、失败 pending 清理和重试
- `JsonStateStore` 对账户、网格 ledger、轮动调仓状态、成交快照、订单状态和运行 metadata 的保存/恢复
- `QuantPipeline.run_once()` 单轮策略执行、订单状态流转、监控更新，以及启动/停止状态恢复保存

## 下一步路线

优先级从高到低：

1. 补强测试和主循环可测性。
2. 明确 adapter 的 mock/real 模式和数据契约。
3. 扩展历史行情驱动的回测引擎。
4. 持久化账户、成交和策略状态。
5. 完善监控报告和告警闭环。
6. 在模拟和回测稳定后，再预研 QMT/实盘执行。

实盘相关能力必须在显式配置、充分测试和状态可恢复后再启用。
