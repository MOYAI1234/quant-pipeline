# 策略因子来源扫描 - 2026-06-19

本记录用于把“找策略因子”这一步变成可审计输入。筛选标准优先考虑 ETF 投资助手定位：中低频、低换手、可用公开平台复现、不依赖高密度交易或不可实现成交假设。

## 筛选原则

- 优先低频资产配置、ETF 轮动、风险开关和仓位分配因子。
- 个股截面 Alpha、机器学习预测和高频执行类仓库先作为后备研究源，不直接进入首批 ETF 候选。
- 来源必须记录链接、星标数量、许可证或引用限制；没有明确许可证的代码不复制，只借鉴公开策略思想并重新实现。
- 本地回测只做 sanity check；公开平台验证仍是策略有效性的主要证据。

## 来源扫描

| 来源 | 星标 | 许可证 | 方向 | 可迁移性 | 初步判断 |
|---|---:|---|---|---|---|
| [alexjansenhome/GEM](https://github.com/alexjansenhome/GEM) | 60 | 未声明 | Global Equities Momentum / 双动量 | 高：月频、ETF、股票/债券/现金切换 | 登记候选 `ETF-DUAL-MOM-002`，代码不复制 |
| [oronimbus/tactical-asset-allocation](https://github.com/oronimbus/tactical-asset-allocation) | 50 | MIT | TAA、DAA、PAA、AAA 等低频资产配置 | 高：多为月频、资产配置框架，适合 ETF 池 | 登记候选 `ETF-DAA-003` |
| [garroshub/Quant_Sector_Rotation_Strategy](https://github.com/garroshub/Quant_Sector_Rotation_Strategy) | 11 | MIT | 行业 ETF 轮动，MA Energy + VIX 仓位 | 中：逻辑接近已有动量，但多均线能量和 VIX 仓位值得拆因子 | 后续作为行业轮动增强候选 |
| [tanish35/Momentum-Investing](https://github.com/tanish35/Momentum-Investing) | 9 | 未声明 | 市场状态、TSMOM、截面动量、FIP、偏度、逆波动 | 中：偏个股，但 FIP/偏度/逆波动可迁移到 ETF | 后续作为因子增强来源，代码不复制 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 44786 | MIT | Alpha158/Alpha360、模型训练、因子研究平台 | 中：偏研究基础设施，不是单一 ETF 策略 | 作为未来因子挖掘和公开基线参考 |
| [wilsonfreitas/awesome-quant](https://github.com/wilsonfreitas/awesome-quant) | 26877 | 未声明 | 量化资源索引 | 中：适合扩展来源池 | 作为持续发现入口 |
| [Menooker/KunQuant](https://github.com/Menooker/KunQuant) | 292 | Apache-2.0 | 金融表达式/因子执行器 | 低到中：更像因子计算基础设施 | 暂不登记策略候选 |
| [laox1ao/Alpha101-WorldQuant](https://github.com/laox1ao/Alpha101-WorldQuant) | 62 | 未声明 | WorldQuant Alpha101 | 低：偏个股截面、频率较高、许可不清 | 暂列观察，不进入 ETF 低频首批 |
| [627378329/dual-etf-momentum-rotation](https://github.com/627378329/dual-etf-momentum-rotation) | 1 | MIT | A 股沪深 300 + 黄金双 ETF 动量 | 中：A 股 ETF 口径接近，但样本和关注度有限 | 可作为 `ETF-DUAL-MOM-002` 本地对照 |

## 首批候选

| 优先级 | 策略 ID | 候选 | 原因 | 下一步 |
|---|---|---|---|---|
| P0 | `ETF-DUAL-MOM-002` | 全球/跨资产双动量 ETF v1 | 月频、低换手，明确风险资产与防御资产切换，正好修正周频动量成本敏感问题 | 用 TuShare ETF 池做本地月频 sanity check，再准备聚宽脚本 |
| P0 | `ETF-DAA-003` | 防御型资产配置 DAA v1 | 使用 canary/breadth 风险开关，强调熊市降风险和回撤控制 | 先实现信号诊断，确认 A 股 ETF 池能否构造 canary 与防御资产 |
| P1 | 待定 | 行业 ETF MA Energy 轮动 | 行业 ETF 可解释性强，多均线能量可能改善单窗口动量 | 等 P0 跑完后再登记 |
| P1 | 待定 | FIP/偏度/逆波动增强 | 可作为 ETF 动量质量因子的增强项 | 先拆成因子实验，不单独上策略 |

## 立即结论

- 不建议继续扩大周频动量交易次数；上一版本地回测显示 0.10% 滑点会显著吞噬收益。
- 下一轮应优先测试月频策略，并强制保留 5 元最低佣金、0.05%-0.10% 滑点和成交额过滤。
- 如果 `ETF-DUAL-MOM-002` 与 `ETF-DAA-003` 在本地都无法显著改善回撤/换手，再回到因子增强，而不是继续调参周频动量。

## 2026-06-20 路线校准

后续本地验证显示，`ETF-DUAL-MOM-002` 和 `ETF-DAA-003` 虽然降低了交易频率或引入风险开关，但最大回撤仍明显高于稳健 ETF 助手的目标区间。因此本扫描中的 P0 排序保留为历史输入，不再代表当前主线优先级。

当前路线改为：

- `ETF-MOM-ROT-001`、`ETF-DUAL-MOM-002`、`ETF-DAA-003` 统一作为 baseline/watchlist，用于对照不同动量和风险开关方案。
- 下一轮优先寻找低回撤多资产配置方向：股债黄金现金配置、风险平价、目标波动率、全天候/永久组合、绝对动量降仓。
- 只有本地 sanity check 接近最大回撤 10%-15% 区间，且费用、滑点、换手和成交约束可解释，才进入公开平台验证。
