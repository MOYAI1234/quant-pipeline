# PRD v3 差距审计与迭代路线图

首次审计：2026-06-01
最近更新：2026-06-18
代码基线：`aca201c` (`master`)
PRD 来源：`D:\claudecode\docs\misc\quant-assistant-prd-v3.md`

## 结论

当前代码已经达到研究/模拟验证版交付基线：数据、策略、模拟执行、风控、状态恢复、监控、CLI 和内部回测均有可重复验收入口，离线测试、provider 演练和回测产物审计已经收口。

但从 PRD v3 的完整目标看，当前项目仍不是“完整 ETF 量化交易系统”。真实实时数据、公开平台策略交叉验证、券商订单状态机、QMT、API/Web 和外部通知仍未交付，因此不能把当前版本解释为生产实盘版。

下一阶段重点从“补工程地基”转为“验证真实数据与策略假设”：真实 provider 验收、真实历史回测、公开平台交叉验证，之后才是模拟盘和小资金实盘预研。

## 当前验证结果

已在 `D:\claudecode\quant-pipeline` 执行：

```powershell
python scripts\verify_offline.py
```

结果：

- `compileall` 通过
- 离线 `pytest` 通过，`405 passed, 2 skipped`
- CLI help 可用
- CLI daily report 可生成包含数据源健康状态和缓存策略的空组合报告
- CLI health 可输出数据源健康状态
- CLI diagnose 可汇总配置、风险 warning、数据源和状态文件诊断，并输出启动阻断原因
- CLI alerts 可输出本地告警事件
- CLI config validate 可校验内置配置和 JSON 配置文件，并可用 `--strict-warnings` 将真实历史 provider 禁用缓存等风险 warning 作为门禁失败；JSON 输出包含 `strict_warnings`
- CLI grid backtest 可生成样例回测报告
- CLI rotation backtest 可生成多 ETF 样例回测报告
- grid / rotation 的 Markdown 和五类 CSV 产物通过 schema、组合一致性和确定性复验

## PRD 对照状态

| PRD 模块 | 当前状态 | 评价 |
|---|---|---|
| 数据适配层 | 部分完成 | 适配器类已存在；`mx_data.history` 已支持命名外部命令 provider 的凭据门禁、同源重试、顺序降级和最近失败链状态，提供 AKShare / TuShare 可选示例脚本、命令 provider 契约和显式启用的 guarded live e2e；但 `mx-xuangu` / `mx-search` / `jason-kb` 以及 `mx-data` 的实时/净值/列表仍是 stub，未接真实服务 |
| 数据管理器 | 部分完成 | `DataManager` 和 TTL 缓存已存在，已覆盖基础字段、数值类型、非负单位、可选行情时效、无时区 timestamp 的显式源时区解释、可配置历史缓存 TTL、缓存策略健康输出、缓存过期和 adapter 异常传播；仍缺更完整单位归一 |
| 网格策略 | 基础可用 | 已支持多格买入、按实际成交股数更新 ledger、部分成交补齐或退出、卖出后允许再买；仍缺更丰富行情路径测试 |
| 行业轮动策略 | 基础可用 | 已支持动量选择、卖旧买新、部分成交/失败批次不更新完成时间并允许重试；仍缺风控冲突场景覆盖 |
| 回测功能 | 已启动 | 已新增最小 `BacktestRunner`、`RotationBacktestRunner` 和 `BacktestExecutionModel`，支持历史 bar、CSV、JSON 驱动、基础回测指标、滑点、成交量参与率限制、可选整手部分成交、拒单归因、逐期组合快照导出和 DataManager 历史数据到回测 CSV 的转换入口；仍缺交易所官方日历、复杂组合、多策略和真实历史数据源 |
| 模拟执行器 | 基础可用 | 买卖、整手、均价、买卖双边费率、单笔最低佣金、估值和部分盈亏计算已实现；回测层已抽出 `BacktestExecutionModel` 统一处理滑点、成交量参与率限制、可选整手部分成交和成交前拒单归因，但仍不支持未成交余量跨 bar 结转和更复杂撮合 |
| QMT/实盘执行 | 未完成 | `qmt_executor.py` 不存在，实盘订单模型、状态同步、异常恢复都未开始 |
| 风控模块 | 部分完成 | 仓位、ETF 质量、止损已存在；但真实 ETF 指标缺失，规则和策略目标可能冲突 |
| 宏观/ETF/新闻分析 | 部分完成 | 分析器结构存在，但依赖 stub 数据，当前更多是接口占位 |
| 监控告警 | 部分完成 | 状态指标、报告和结构化告警事件已存在，报告可展示最近告警摘要，并支持本地 JSONL 输出；外部通知通道尚未实现 |
| CLI | 基础可用 | `start/status/report/health/diagnose/alerts/config show/config init/config validate/backtest/history probe/history export-grid/history export-rotation` 已有；配置初始化、查看、校验和运行诊断链路已具备 |
| API/Web | 未完成 | PRD 中规划了 API 和 Web 界面，当前仓库没有对应模块 |
| 测试体系 | 研究版可交付 | 现有 405 个离线测试和 2 个默认跳过的 AKShare / TuShare guarded live test，覆盖策略状态机、风控、模拟执行、回测成交模型、数据契约、provider 降级、状态恢复、监控报告、CLI、回测产物 schema 与确定性；生产阶段仍需真实订单状态机、长时间运行和故障注入测试 |
| 文档入口 | 研究版可交付 | README、架构、测试、provider 契约与演练、真实数据验收、交付状态和公开平台交叉验证入口已经形成 |

回测能力细节：

- 输入格式：`BacktestRunner` 支持历史 bar list/CSV 驱动 grid 策略；`RotationBacktestRunner` 支持内置多 ETF 样例、JSON snapshot 和 CSV 长表驱动 rotation 策略。
- 转换入口：`history export-grid/export-rotation` 可把本地 JSON 或 `DataManager.get_etf_history()` 返回的真实历史行情转换为 grid CSV 或 rotation CSV 长表。
- 校验规则：grid 回测已覆盖历史日期/盘中时间顺序、OHLC 合法性、价格、成交量和成交额校验；rotation 回测已覆盖 JSON 基础结构和 CSV 长表聚合校验。
- 执行模型：`BacktestExecutionModel` 统一处理比例滑点、成交量参与率限制、同一 bar 内成交量占用、可选整手部分成交和成交前拒单归因，再交给 `Simulator` 执行。
- 输出产物：两类 runner 均复用 `Simulator` 输出收益、最大回撤、最大回撤区间、交易次数、拒单次数与原因、胜率、总手续费及其初始资金占比，并支持 Markdown 回测报告以及权益曲线、组合快照、成交明细、持仓明细和拒单明细 CSV 导出；组合快照会保留现金、持仓市值、总值、已实现/未实现盈亏和 `total_value_delta` 一致性校验列。
- 配置选项：CLI 已支持 `backtest --strategy grid|rotation`、回测日期区间过滤、比例滑点、可选成交量参与率限制、可选整手部分成交和可选严格交易日历。
- 缺失能力：交易所官方日历、未成交余量结转、复杂组合回测、多策略编排和真实历史数据源仍未实现。

## 主要风险

### P0：真实数据覆盖仍不足，系统尚不能产生生产级信号

adapter 已显式区分 `mock|real`，未配置的 real 能力会标记不可用；历史行情可通过命令 provider 接入 AKShare / TuShare，并具备凭据门禁、重试、降级和健康输出。但实时行情、ETF 列表、新闻、宏观情绪和筛选结果仍主要是 mock/stub，真实 provider 也尚无生产 SLA。

风险：

- 策略无法基于真实市场数据运行
- 风控里的流动性、规模、溢价检查没有真实依据
- CLI/主循环可能“正常运行但没有业务价值”

建议：

- 显式运行 AKShare / TuShare guarded live e2e，并持续记录 provider 可用性
- 用真实历史输入完成内部回测和公开平台交叉验证
- 为后续实时、筛选和新闻 adapter 延续 `mock|real`、最小查询和结构化错误契约

### P0：内部回测已启动，但仍缺公开平台交叉验证

PRD 将“可回测策略系统”列为阶段二交付物。当前仓库已经有内部回测 runner，用于验证本系统的策略状态机、风控、执行模型、报告和导出产物；但内部回测不能单独证明策略可生产，仍需要公开回测平台做外部结果交叉验证。

风险：

- 内部回测可能与公开平台在数据源、复权、交易日历、手续费、滑点和撮合模型上存在差异
- 只依赖内部回测，容易把工程链路跑通误判为策略可生产
- 实盘前仍缺“内部自验证 → 公开平台交叉验证 → 模拟盘/小资金实盘预研”的分层门槛

建议：

- 保留项目内回测作为 CI 和工程回归验收入口
- 在聚宽、优矿、米筐等公开回测平台中至少选择一个复现关键策略假设
- 对收益、调仓、成交、复权、交易日历、手续费和滑点差异做记录
- 只有内部自验证通过且公开平台差异可解释，才进入模拟盘或小资金实盘预研

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

### P1：研究版高风险路径已覆盖，生产路径仍未验证

rotation 首次调仓、卖旧买新、失败重试，stop-loss 后 ledger 同步，RiskManager 边界，`QuantPipeline.run_once()`，DataManager 缓存与异常传播均已有离线测试。剩余风险主要转向真实 provider 长时间运行、券商回报、进程中断恢复、故障注入和生产监控，不应继续用增加 mock 单元测试代替真实链路验证。

### P1：风控和策略目标可能互相打架

例如 rotation 希望等权买入 top_n ETF，但 `max_single_weight` / `max_position` 可能导致订单被拒绝。当前缺少策略层对风控拒绝原因的可解释处理。

建议：

- 将风控结果结构化：`code`、`message`、`severity`、`retryable`
- 策略接收失败原因，而不只是递减 pending
- 为策略配置目标仓位时同步生成风控配置建议

### P2：交付文档已形成，需要持续防止状态漂移

README、testing、architecture、provider 契约与演练、live 验收、交付状态和公开平台验证模板已经形成。后续每次改变测试基线、数据契约、成交假设或阶段门槛时，需要同步这些入口，避免代码已交付而路线图仍停留在旧状态。

## 建议迭代路线

### M0：工程基线与测试补强

状态：研究/模拟版已完成。rotation、RiskManager、StopLoss、主循环单 tick、CLI smoke 和基础文档均已覆盖。

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

状态：研究/模拟版已完成。adapter 支持显式 `mode=mock|real`，结构化健康检查会暴露 `mode`、`connected`、`available`、`mock` 和 `error`。历史行情 real 模式可接命令 provider；其他未配置的 real 能力会明确返回不可用并抛出 `ServiceUnavailableError`。`DataManager` 会校验实时行情、净值和历史行情的基础字段、数值类型、非负单位、可选时效、无时区 timestamp 的源时区解释和 adapter 异常传播。

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

状态：研究/模拟版已完成。`BacktestRunner` 与 `RotationBacktestRunner` 支持内置样例、CSV/JSON 和 provider 导出的历史输入；`BacktestExecutionModel` 统一处理滑点、成交量参与率、同 bar 成交量占用、可选整手部分成交和拒单归因。CLI 可导出 Markdown、权益、组合、成交、持仓和拒单产物，并通过 manifest、schema、组合一致性和确定性复验。当前仍不包含交易所官方日历、复杂组合和多策略编排，仓库也不内置真实行情或凭据。

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

状态：研究/模拟版已完成。`Simulator`、`GridStrategy`、`RotationStrategy` 和 `OrderManager` 支持 snapshot/restore，`JsonStateStore` 可保存账户、策略、内部订单和运行 metadata，并具备旧版快照到 v1 的最小迁移。生产阶段仍缺真实券商订单回报、完整多版本迁移和持久化数据库。

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

状态：研究/模拟版已完成。CLI health/diagnose、日报/周报、结构化告警、JSONL 输出和 provider/cache 状态摘要均可验收。生产阶段仍缺飞书、邮件等外部通知通道和长期运行监控。

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

研究/模拟版已达到 [交付基线](release-readiness.md)。下一轮不碰实盘接口，进入真实数据与外部策略验证：

1. 显式运行 AKShare / TuShare guarded live e2e，验证 `history probe` 的真实网络链路、账户权限和单位契约。
2. 用实际 provider 配置生成可追溯回测输入；只在本地归档受许可约束的数据和凭据。
3. 运行内部回测产物验收，并按[公开回测平台交叉验证](public-backtest-validation.md)在至少一个平台复现关键策略假设。
4. 使用真实费率、最低佣金、滑点和成交量约束，筛除依赖高密度网格交易才能成立的参数。
5. 只有差异可解释且保守成本下结论不反转，才规划模拟盘或小资金实盘预研。
