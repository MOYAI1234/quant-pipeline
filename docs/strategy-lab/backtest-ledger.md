# 回测与验证流水账

本文件统一记录本地 simulator、公开平台、未来模拟盘或小资金验证结果。它不是收益展示页，而是研究审计台账。

## 记录字段

每次验证至少记录：

| 字段 | 说明 |
|---|---|
| 日期 | 运行或记录日期 |
| 策略/因子 | 策略 ID 或因子名称 |
| 平台 | 本地 simulator / 聚宽 / 优矿 / 米筐 / 模拟盘 / 小资金 |
| 区间 | 样本内、样本外或实盘观察区间 |
| 参数版本 | lookback、调仓频率、资产池、费用、滑点、初始资金 |
| 年化收益 | 扣费后 |
| 最大回撤 | 含区间更好 |
| 回撤恢复 | 如可获得，记录恢复用时 |
| 交易频率 | 交易次数、换手或成交额占初始资金 |
| 结论 | `baseline` / `watchlist` / `candidate` / `rejected` |
| 产物 | 脚本、PR、截图说明或平台导出摘要 |

## 已有验证记录

| 日期 | 策略/因子 | 平台 | 区间 | 参数版本 | 年化收益 | 最大回撤 | 交易频率/费用 | 结论 | 产物 |
|---|---|---|---|---|---|---|---|---|---|
| 2026-06-18 | `ETF-MOM-ROT-001` | 本地 simulator | 2015-07-01 至 2021-12-31 | 周频，60/20/20，最多 2 只，10 万本金，最低佣金 5 元，滑点 0.10% | +0.72% | 24.89% | 成交额/初始资金 10491.67%，费用 3204.75 | `baseline` | [策略档案](../strategy-candidates/etf-momentum-rotation-v1.md) |
| 2026-06-19 | `ETF-DUAL-MOM-002` | 本地 simulator | 2015-07-01 至 2021-12-31 | 120 日动量，月频，风险资产 4 只，防御资产 518880 | +14.00% | 28.86% | 成交额/初始资金 6585.30%，费用 1975.59 | `baseline` | [策略档案](../strategy-candidates/etf-dual-momentum-v1.md) |
| 2026-06-19 | `ETF-DUAL-MOM-002` | 本地 simulator | 2015-07-01 至 2021-12-31 | 252 日动量，TuShare 交集交易日 1585 条 | +10.32% | 27.50% | 成交额/初始资金 1814.17%，费用 544.25 | `baseline` | [策略档案](../strategy-candidates/etf-dual-momentum-v1.md) |
| 2026-06-19 | `ETF-DUAL-MOM-002 + 15% 暂停` | 本地 simulator | 2015-07-01 至 2021-12-31 | 252 日动量，组合回撤 15% 暂停 | +10.92% | 27.57% | 成交额/初始资金 2534.82%，费用 760.44 | `baseline` | [策略档案](../strategy-candidates/etf-dual-momentum-v1.md) |
| 2026-06-19 | `ETF-DAA-003` | 本地 simulator | 2015-07-01 至 2021-12-31 | 120 日动量，canary=510500，breadth 阈值 50% | +11.15% | 28.86% | 成交额/初始资金 4959.32%，费用 1487.80 | `watchlist` | [策略档案](../strategy-candidates/etf-defensive-asset-allocation-v1.md) |

## 待补验证

| 优先级 | 策略/因子 | 平台 | 目标 |
|---|---|---|---|
| P0 | ETF 趋势防守 | 本地 + 聚宽 | 验证 ETF 主线下的降仓/空仓风控能否压低最大回撤 |
| P0 | ETF 核心池轮动 | 本地 + 聚宽 | 验证宽基/行业 ETF 池内轮动能否兼顾收益和回撤 |
| P0 | 目标仓位控制 | 本地 + 聚宽 | 验证降仓规则和回撤控制 |
| P0 | `ETF-TREND-GUARD-004` | 聚宽 | 复制 [etf_trend_guard_v1.py](../../examples/joinquant/etf_trend_guard_v1.py) 跑公开平台回测 |
| P0 | `ETF-CORE-ROT-GUARD-005` | 聚宽 | 复制 [etf_core_rotation_guard_v1.py](../../examples/joinquant/etf_core_rotation_guard_v1.py) 跑公开平台回测 |
| P1 | `ETF-DUAL-MOM-002` | 聚宽 | 作为月频动量对照，而不是稳健候选 |
| P1 | `ETF-MOM-ROT-001` | 聚宽 | 作为周频成本敏感对照 |
