# 数据源 provider 选型矩阵

评估日期：2026-06-11

本项目当前仍处于 mock/simulator 阶段，真实历史行情只通过 mx_data.history_command 预留外部命令式 provider 接入位。本文用于记录 mx-data 之外的候选数据源，不在本轮直接引入依赖或提交 API key。

## 结论

优先顺序：

1. **AKShare**：作为第一优先 POC。社区规模最大、MIT 许可、维护活跃，适合先接日级 ETF 历史行情和基础行情探测。
2. **a-stock-data**：作为第二候选。定位是多数据源统一工具包，Apache-2.0，适合作为“多源降级/统一输出”的参考，但需要先验证 ETF 覆盖和接口稳定性。
3. **TuShare**：作为补充候选。社区规模大、BSD-3-Clause，但常见使用路径涉及 token、积分或服务侧限制，适合作为后续可配置 provider，不适合作为默认无凭据方案。
4. **qstock**：作为研究型备选。MIT，接口和投研功能较完整，但项目更新节奏低于 AKShare，适合参考，不建议先接入生产主路径。
5. **BaoStock GitHub 镜像/脚本类仓库**：暂缓。GitHub star 低、维护形态更像示例脚本集合，不满足“高 star 整合数据源包”的主诉求。

## 候选矩阵

| 候选 | GitHub | Star / Fork | License | 最近活跃度 | 初步定位 | 主要风险 |
|---|---|---:|---|---|---|---|
| AKShare | [akfamily/akshare](https://github.com/akfamily/akshare) | 20240 / 3265 | MIT | 2026-06-11 updated，2026-05-27 pushed | 第一优先 POC：ETF 日级历史、行情探测、后续多资产扩展 | 上游接口可能受网页源变化影响；需做字段校验、重试和缓存 |
| AKTools | [akfamily/aktools](https://github.com/akfamily/aktools) | 1404 / 234 | MIT | 2026-06-10 updated，2025-10-29 pushed | AKShare HTTP 化参考，不优先作为核心依赖 | 多一层服务部署和运维，不适合当前最小 provider |
| TuShare | [waditu/tushare](https://github.com/waditu/tushare) | 15114 / 4437 | BSD-3-Clause | 2026-06-11 updated，2024-03-13 pushed | 有凭据/积分路径的补充 provider | token、积分、频率和服务条款需要显式配置，不适合作默认无凭据 provider |
| a-stock-data | [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) | 3803 / 772 | Apache-2.0 | 2026-06-11 updated，2026-06-03 pushed | 多数据源统一层候选，可参考降级策略 | 项目较新，需要验证 ETF 历史覆盖、输出 schema 和异常语义 |
| qstock | [tkfy920/qstock](https://github.com/tkfy920/qstock) | 1847 / 383 | MIT | 2026-06-10 updated，2025-03-16 pushed | 研究型备选，适合补充投研数据 | 依赖和接口边界需验证，优先级低于 AKShare |
| BaoStock 镜像 | [shimencaiji/baostock](https://github.com/shimencaiji/baostock) | 107 / 29 | 未声明 | 2026-06-09 updated，2019-10-25 pushed | 暂缓，仅作为历史参考 | GitHub 维护和许可不清晰，不符合高 star 整合包要求 |

Star、fork、license 和活跃度来自 GitHub 仓库元信息。GitHub 的 updated_at 可能由 issue、star 等事件触发，不能单独代表代码发布频率，因此同时记录 pushed_at。

## 对 ETF 投资助手的生产约束

ETF 投资助手的默认方向应是低频、可解释、成本可承受的组合辅助，不应把高密度网格交易作为生产默认路径。

接入真实数据源后，任何回测报告都必须继续保留：

- 买入/卖出佣金率、最低佣金和滑点配置。
- 总成交额、成交额占初始资金、每周期交易次数。
- 已平仓手续费/毛盈利。
- grid 一轮整手估算、扣费后净收益和生产可行性警告。

如果某个策略只有在非常密集网格、忽略最低佣金、忽略滑点或高频成交假设下才盈利，应在报告中视为不可生产参数，而不是进入实盘预研。

## 推荐接入顺序

### POC 1：AKShare 命令式历史 provider

目标：新增一个仓库外部脚本或文档化命令，供现有 mx_data.history_command 调用，输出当前 history probe 能校验的 JSON。

验收：

- 支持 ETF 日级历史行情。
- 输出字段至少包含 date/open/high/low/close/volume/amount。
- 能通过 python cli\commands.py history probe --config ...。
- 缺字段、无数据、乱序日期、越界日期会被现有 DataManager / probe 拒绝。
- 不提交任何 token、cookie 或私有 provider 路径。

### POC 2：a-stock-data 输出 schema 验证

目标：验证它是否能稳定输出 ETF 历史行情，并评估其多源降级是否值得纳入 adapter 设计。

验收：

- 与 AKShare POC 使用相同 history JSON contract。
- 明确异常时返回方式：空列表、错误码、异常、stderr。
- 明确是否适合仓库内依赖，还是仅适合外部命令 provider。

### POC 3：TuShare 可选 provider

目标：只在用户本地显式配置 token 后启用，不能成为默认 provider。

验收：

- config 中必须显式声明 token 来源和服务限制。
- config validate / diagnose 能在 token 缺失时给出清楚错误。
- README 明确不要提交 token 或缓存的私有数据。

## 暂不做

- 不把 provider 包直接加入 requirements.txt。
- 不在仓库内保存真实行情 CSV 样本，除非样本明确可公开且体量可控。
- 不绕过现有 history probe / DataManager 字段校验。
- 不因为某个数据源能取分钟级数据，就把产品方向改成高频或密集网格。

## 后续 PR 建议

1. 使用 examples/providers/akshare_history_provider.py 配置本地 AKShare POC，并通过 history probe 验证真实返回。
2. 继续完善 docs/history-provider-contract.md，必要时加入 provider 错误样例和常见排障。
3. 使用本地真实 provider 配置执行 guarded e2e，只提交文档和测试，不提交凭据。
