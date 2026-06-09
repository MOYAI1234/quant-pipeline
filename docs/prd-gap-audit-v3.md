# PRD v3 差距审计与迭代路线图

审计日期：2026-06-01
代码基线：`e7d60f1` (`master`)，并包含当前 M4 report health 分支增量
PRD 来源：`D:\claudecode\docs\misc\quant-assistant-prd-v3.md`

## 结论

当前代码已经具备量化助手 Pipeline 的基础分层：数据、策略、执行、风控、分析、监控和 CLI 都有落点；网格策略、轮动策略和模拟执行器也经过了第一轮集成修复，基础测试可通过。

但从 PRD v3 的完整目标看，当前项目仍处于“模拟交易内核 + 产品骨架”阶段，尚未达到“完整 ETF 量化交易系统”。最大缺口在真实数据适配、回测、状态持久化、实盘执行、API/Web、监控告警闭环和系统级测试。

建议下一阶段不要急于扩展更多策略，而是优先把“数据可信、状态可恢复、测试可复现、回测可验证”四件事补齐。

## 当前验证结果

已在 `D:\claudecode\quant-pipeline` 执行：

```powershell
python -m compileall -q .
python -m pytest -q
python cli\commands.py --help
python cli\commands.py report --type daily
python cli\commands.py health
python cli\commands.py alerts
python cli\commands.py config validate
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy rotation
```

结果：

- `compileall` 通过
- `pytest` 通过，`259 passed`
- CLI help 可用
- CLI daily report 可生成包含数据源健康状态的空组合报告
- CLI health 可输出数据源健康状态
- CLI alerts 可输出本地告警事件
- CLI config validate 可校验内置配置和 JSON 配置文件
- CLI grid backtest 可生成样例回测报告
- CLI rotation backtest 可生成多 ETF 样例回测报告

## PRD 对照状态

| PRD 模块 | 当前状态 | 评价 |
|---|---|---|
| 数据适配层 | 部分完成 | 适配器类已存在，但 `mx-data` / `mx-xuangu` / `mx-search` / `jason-kb` 基本仍是 stub，未接真实服务 |
| 数据管理器 | 部分完成 | `DataManager` 和 TTL 缓存已存在，已覆盖基础字段、数值类型、非负单位、可选行情时效、无时区 timestamp 的显式源时区解释、缓存过期和 adapter 异常传播；仍缺更完整单位归一 |
| 网格策略 | 基础可用 | 已支持多格买入、成交确认后更新 ledger、卖出后允许再买；仍缺持久化和更丰富行情路径测试 |
| 行业轮动策略 | 基础可用 | 已支持动量选择、卖旧买新、失败回调；仍缺独立测试和风控冲突场景覆盖 |
| 回测功能 | 已启动 | 已新增最小 `BacktestRunner` 和 `RotationBacktestRunner`，可用历史 bar / 多 ETF 样例、JSON snapshot 或 CSV 长表驱动 grid、rotation 策略并复用 `Simulator` 输出收益、最大回撤、最大回撤区间、交易次数、拒单次数与原因、胜率、总手续费及其初始资金占比、带逐期收益/回撤列的权益曲线 CSV、成交明细 CSV、持仓明细 CSV、拒单明细 CSV、可配置滑点、可选成交量参与率限制和可选严格交易日历等基础指标，CLI 已支持回测日期区间过滤、历史日期/盘中时间顺序、grid OHLC 合法性校验、rotation JSON 基础结构校验和 rotation CSV 长表聚合校验；仍缺交易所官方日历、部分成交、复杂组合、多策略和真实历史数据源 |
| 模拟执行器 | 基础可用 | 买卖、整手、均价、手续费、估值和部分盈亏计算已实现；回测 runner 可选限制 bar 成交量参与率，超限订单按失败处理，但仍不支持部分成交和更复杂撮合 |
| QMT/实盘执行 | 未完成 | `qmt_executor.py` 不存在，实盘订单模型、状态同步、异常恢复都未开始 |
| 风控模块 | 部分完成 | 仓位、ETF 质量、止损已存在；但真实 ETF 指标缺失，规则和策略目标可能冲突 |
| 宏观/ETF/新闻分析 | 部分完成 | 分析器结构存在，但依赖 stub 数据，当前更多是接口占位 |
| 监控告警 | 部分完成 | 状态指标、报告和结构化告警事件已存在，报告可展示最近告警摘要，并支持本地 JSONL 输出；外部通知通道尚未实现 |
| CLI | 基础可用 | `start/status/report/health/alerts/config validate/backtest` 已有；仍缺更完整的配置解释、初始化和运行诊断命令 |
| API/Web | 未完成 | PRD 中规划了 API 和 Web 界面，当前仓库没有对应模块 |
| 测试体系 | 不足 | 现有 247 个测试覆盖 simulator、grid e2e、rotation、risk manager 边界、backtest runner、回测日期区间、历史日期/盘中时间顺序、OHLC 合法性、成交量参与率、拒单审计和可选交易日历校验、回测最大回撤区间、回测手续费统计、权益曲线/成交明细 CSV 导出、回测滑点、CLI smoke、状态持久化、报告健康状态、告警事件、配置校验、DataManager 缓存与数据契约等；adapter、report 仍有缺口 |
| 文档入口 | 不足 | `README.md` 已补充基础运行、测试和阶段边界；仍缺 `docs/testing.md`、`docs/architecture.md` 等专题文档 |

## 主要风险

### P0：真实数据不可用时，系统无法产生可信信号

当前所有外部适配器都能 `connect()`，但返回的是默认值或空列表。这样会让 health check 呈现“正常”，但实际没有真实行情、ETF 列表、新闻、宏观情绪或筛选结果。

风险：

- 策略无法基于真实市场数据运行
- 风控里的流动性、规模、溢价检查没有真实依据
- CLI/主循环可能“正常运行但没有业务价值”

建议：

- 为每个 adapter 定义真实/模拟两种模式
- stub 模式要显式标识为 `mock` 或 `unavailable`
- health check 必须验证最小可用数据，而不只是 `connected=True`
- 引入统一错误类型：服务不可用、空结果、数据过期、字段缺失、单位不一致

### P0：缺少回测引擎，策略无法被历史数据验证

PRD 将“可回测策略系统”列为阶段二交付物，但当前只有实时/模拟执行路径，没有历史行情驱动。

风险：

- 无法判断策略参数是否有效
- 后续策略迭代只能依赖人工推演和少量单测
- 实盘前缺少关键验收门槛

建议：

- 新增 `backtest/` 或 `analysis/backtest.py`
- 统一复用策略的 `generate_signal` 和执行器成交逻辑
- 支持历史 K 线输入、手续费、滑点、交易日历、收益/回撤/胜率报告
- CLI 增加 `backtest` 子命令

### P1：状态持久化仍缺迁移策略和真实订单回报

网格 `grid_ledger`、轮动 `last_rebalance` / `pending_rebalance_count`、模拟账户持仓、成交记录、pipeline 内部订单状态和运行 metadata 已具备 snapshot/restore 与 JSON 保存/恢复入口，`QuantPipeline` 也已支持启动恢复和停止保存。

风险：

- 当前已有 pending/filled/failed/rejected 的内部订单状态，但还不是 QMT/券商报单回报状态机
- 状态版本已有旧版无顶层 `version` 状态到 v1 的最小迁移入口，但还没有完整多版本迁移策略
- 实盘接入前仍缺 submitted/partial/cancelled 等真实订单状态和恢复基础

建议：

- 继续扩展 JSON/SQLite 持久化
- 持久化对象继续补充真实订单状态机和更完整的运行审计信息
- 扩展状态版本迁移策略和迁移审计记录

### P1：测试覆盖集中在 grid/simulator，缺少高风险集成路径

当前测试能证明基础模拟器和网格路径可用，但之前多轮 bug 主要来自 rotation、风控拒绝、止损和成交回调的组合路径。

建议优先补：

- rotation 首次调仓成功路径
- rotation 风控拒绝后 pending 清理和重试
- rotation 卖旧买新时现金计算
- stop-loss 触发后策略 ledger 同步
- RiskManager rebalance 的边界
- QuantPipeline 主循环的单 tick 集成测试
- DataManager 缓存过期与 adapter 异常传播

### P1：风控和策略目标可能互相打架

例如 rotation 希望等权买入 top_n ETF，但 `max_single_weight` / `max_position` 可能导致订单被拒绝。当前缺少策略层对风控拒绝原因的可解释处理。

建议：

- 将风控结果结构化：`code`、`message`、`severity`、`retryable`
- 策略接收失败原因，而不只是递减 pending
- 为策略配置目标仓位时同步生成风控配置建议

### P2：产品入口和交付文档不足

仓库已有 `README.md` 说明基础运行、测试和 mock/simulator 阶段边界，但仍缺少更细的开发者专题文档，例如如何接入数据源、如何验收和如何理解架构边界。

建议：

- 持续维护 `README.md`
- 增加 `docs/testing.md`
- 增加 `docs/architecture.md`
- 将 PRD 验收项映射到测试命令和功能状态

## 建议迭代路线

### M0：工程基线与测试补强

目标：让现有模拟内核更可靠，避免后续接数据/回测时反复踩基础状态机问题。

任务：

- 补 rotation 单元测试和 e2e 测试
- 补 RiskManager / StopLoss 测试
- 抽出 `QuantPipeline.run_once()`，让主循环可测试
- 增加 CLI smoke 测试
- 新增 README 和测试说明

验收：

- `pytest` 覆盖 grid、rotation、risk、simulator、CLI smoke
- 主循环至少可用 mock data 跑一个 tick
- 文档说明本地运行方式

### M1：数据适配契约和 mock/real 模式

状态：已启动。当前 adapter 已支持显式 `mode=mock|real`，并通过结构化健康检查暴露 `mode`、`connected`、`available`、`mock` 和 `error`。`real` 模式尚未接入真实外部服务，会明确返回不可用并在数据调用时抛出 `ServiceUnavailableError`。`DataManager` 已开始校验实时行情、净值和历史行情的基础字段、数值类型、非负单位、可选行情时效、无时区 timestamp 的显式源时区解释和 adapter 异常传播，字段缺失、shape 错误、非法字段值或启用时效校验后的过期数据会抛出 `DataFetchError`。`RiskManager` 已补充买入仓位上限、已有标的加仓、单笔权重、无持仓卖出、固定止损、单笔止损、跟踪止损和组合亏损告警的直接边界测试。

目标：让系统能清楚地区分“真实数据可用”和“当前只是模拟数据”。

任务：

- adapter 统一返回 dataclass 或明确 schema dict
- adapter 增加 `mode=mock|real`
- health check 调用真实最小查询
- DataManager 做字段校验、单位归一、时效检查
- 明确 premium、volume、amount、size 等字段单位

验收：

- mock 模式测试稳定
- real 模式不可用时给出明确错误
- 风控不再被默认 `0` 数据误导

### M2：回测引擎

状态：已启动。当前已新增最小 `BacktestRunner`，支持单策略、单标的、历史 bar list/CSV 输入，并校验价格、成交量/成交额和 OHLC 区间一致性；并新增 `RotationBacktestRunner`，支持内置多 ETF 历史样例、外部 JSON snapshot 或 CSV 长表驱动行业轮动。两者均复用 `Simulator` 输出收益、最大回撤、最大回撤区间、交易次数、拒单次数与原因、按已平仓卖出统计的胜率、总手续费及其初始资金占比等基础指标；CLI 已增加 `backtest --strategy grid|rotation`，并支持 `--start-date` / `--end-date` 过滤回测区间、历史日期/盘中时间严格递增校验、可选严格交易日历、`--slippage-rate` 比例滑点、`--max-volume-participation` 成交量参与率限制、`--equity-output` 权益曲线 CSV 导出、`--trades-output` 成交明细 CSV 导出、`--positions-output` 逐期持仓明细 CSV 导出和 `--rejections-output` 拒单明细 CSV 导出。权益曲线 CSV 已包含逐期收益率和回撤列，持仓明细 CSV 会保留逐期标的、份额、成本、市值和浮动盈亏，拒单明细 CSV 会保留拒单归因和策略原始信号原因。该能力仍是 M2 起步版，不包含交易所官方日历、部分成交、复杂组合回测、多策略编排和真实历史数据源。

目标：让策略在历史数据上可验证。

任务：

- 新增回测 runner
- 复用 Simulator 做成交
- 支持手续费、滑点、初始资金、日期区间
- 输出收益、最大回撤、最大回撤区间、胜率、交易次数、持仓曲线/权益曲线
- CLI 增加 `backtest`

验收：

- grid 可跑历史样例数据
- rotation 可跑多 ETF 历史样例数据
- 回测结果可生成 Markdown 报告

### M3：状态持久化

状态：已启动。当前已为 `Simulator`、`GridStrategy`、`RotationStrategy`、`OrderManager` 增加 `snapshot()` / `restore()`，并新增 `JsonStateStore` 支持账户、策略状态、内部订单状态和运行 metadata 的 JSON 保存/恢复；`QuantPipeline` 默认会在启动时恢复、停止时保存，CLI 支持 `--state-path` 和 `--no-state`。metadata 已记录 `last_run_at` 和 `last_market_time_by_symbol`，订单会随 pipeline 执行更新为 pending/filled/failed/rejected。状态文件已具备旧版无顶层 `version` 快照到 v1 的最小迁移入口和迁移循环保护。该能力仍是 M3 起步版，尚未覆盖真实券商订单回报、完整多版本迁移和 SQLite 存储。

目标：长期模拟和未来实盘具备恢复能力。

任务：

- 账户、订单、成交持久化
- 策略状态持久化
- 启动时恢复状态
- 增加状态版本号和迁移策略

验收：

- 程序重启后不会重复买入同一 grid
- rotation 保留 last_rebalance
- 成交记录可追溯

### M4：监控、报告和告警闭环

状态：已启动。当前 CLI 已新增 `health` 命令，可输出数据源健康状态的文本报告，也可通过 `--json` 输出结构化摘要；`--strict` 可在任一 adapter 不可用时返回非零退出码。日报/周报也已包含数据源健康状态块。`AlertManager` 已支持结构化告警事件、内存历史和可选 JSONL 文件输出，`SystemMonitor` 会记录亏损和持仓阈值告警，报告会展示最近告警摘要，`alerts` 命令可查询本地 JSONL 告警事件。该能力仍是 M4 起步版，尚未接入飞书、邮件等外部通知通道。

目标：让系统不仅能跑，还能被观察和复盘。

任务：

- 扩展 ReportGenerator
- 增加风险事件记录
- 增加 adapter health/report
- 通知通道先用 console/file，再考虑飞书/邮件

验收：

- 每日/周度报告包含持仓、交易、风险、数据源状态
- 告警有可测试输出

### M5：实盘/QMT 预研

目标：在模拟和回测成熟后，再进入实盘接口。

任务：

- 定义 QMT executor 接口
- 订单状态机：pending、submitted、filled、partial、cancelled、rejected
- 实盘只允许在显式配置下启用
- 增加 dry-run 和 kill switch

验收：

- 实盘模块默认不可误触
- 所有订单状态可审计

## 下一轮优先任务建议

建议下一轮继续做 M2，不碰实盘接口，先把回测输入和结果审计能力打牢：

1. 抽象回测成交模型，为后续部分成交、限量成交和成交失败归因继续铺路。
2. 增加组合级回测结果导出，覆盖现金、总市值、持仓明细、交易明细和拒单明细的一致性校验。
3. 补充真实历史数据适配层到回测输入格式的转换脚本。
4. 继续补充 `README.md` 和专题文档，明确当前是 mock/simulator 阶段，不是实盘系统。

这组任务风险小、收益高，也最适合作为后续真实数据接入和 QMT 预研前的地基。
