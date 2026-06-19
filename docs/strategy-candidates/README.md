# 策略候选索引

本目录用于登记 ETF 投资助手的策略/因子候选。每个候选都必须先成为可审计记录，再进入本地 sanity check、公开平台验证、模拟盘或小资金预研。这里的记录不是投资建议，也不表示策略已经有效。

新增候选时应复制 [策略候选模板](../strategy-candidate-template.md)，并至少补齐来源、核心假设、标的池、因子定义、调仓规则、成本约束、风险和验证计划。

## 状态定义

| 状态 | 含义 |
|---|---|
| `idea` | 只有策略想法，尚未完成完整记录 |
| `researching` | 已记录假设和验证计划，正在准备本地或公开平台验证 |
| `backtested` | 已完成本地 sanity check，但尚未完成公开平台交叉验证 |
| `rejected` | 假设失效、成本后失效、不可复现或风险不可接受 |
| `watchlist` | 逻辑有价值，但证据不足或等待更多样本 |
| `candidate` | 本地 sanity check 和公开平台初步验证均通过，可设计模拟盘方案 |
| `simulated` | 已进入模拟盘观察 |
| `small_live` | 已进入小资金实盘预研 |

## 当前候选

| 策略 ID | 策略名称 | 状态 | 方向 | 当前下一步 |
|---|---|---|---|---|
| `ETF-MOM-ROT-001` | ETF 动量质量轮动 v1 | `researching` | 中低频 ETF 轮动 | 已准备 [聚宽复现脚本](../../examples/joinquant/etf_momentum_rotation_v1.py)，等待公开平台回测结果 |
| `ETF-DUAL-MOM-002` | [全球/跨资产双动量 ETF v1](etf-dual-momentum-v1.md) | `researching` | 月频 ETF 双动量 | 准备本地月频信号诊断和收益回测 |
| `ETF-DAA-003` | [防御型资产配置 DAA v1](etf-defensive-asset-allocation-v1.md) | `researching` | 月频战术资产配置 | 准备 canary/breadth 风险开关信号诊断 |

## 维护规则

- 记录策略来源、引用限制和改写痕迹；来自 GitHub、论文或文章的候选必须保留链接和许可证判断。
- 所有收益、回撤、换手和费用结论必须写明平台、区间、参数版本、复权口径和成本假设。
- 项目内回测只作为工程 sanity check；公开平台验证是策略假设是否值得继续推进的主要证据。
- 依赖高密度网格、低于真实成本的交易频率、无限流动性或未来函数的候选应标记为 `rejected` 或 `watchlist`。
- 不保存 token、账号、私有行情 dump 或受许可限制的数据文件。
