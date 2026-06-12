# 数据源 provider 选型矩阵

评估日期：2026-06-12

本项目当前仍处于 mock/simulator 阶段，真实历史行情只通过 mx_data.history_command 预留外部命令式 provider 接入位。本文用于记录 mx-data 之外的候选数据源，不在本轮直接引入依赖或提交 API key。

## 结论

优先顺序：

1. **AKShare**：第一优先 POC 已完成，已有可选命令 provider 和 guarded live e2e。它仍是研究与本地验收入口，不等于生产 SLA。
2. **a-stock-data**：不作为可直接安装的 provider。它是一个自包含 `SKILL.md`，通过内嵌 Python 代码整合多个上游，适合参考多源优先级、限流和降级设计。
3. **TuShare**：作为下一轮可配置 provider 候选。社区规模大、BSD-3-Clause，但 token、积分、频率和服务条款必须显式配置。
4. **mootdx**：只保留为技术验证候选。虽然代码仓库声明 MIT，官方 README 同时写明“不得用于任何商业目的”，在获得明确授权前不能进入生产依赖。
5. **qstock**：作为研究型备选。MIT，接口和投研功能较完整，但项目更新节奏低于 AKShare，适合参考，不建议先接入生产主路径。
6. **BaoStock GitHub 镜像/脚本类仓库**：暂缓。GitHub star 低、维护形态更像示例脚本集合，不满足“高 star 整合数据源包”的主诉求。

## 候选矩阵

| 候选 | GitHub | Star / Fork | License | 最近活跃度 | 初步定位 | 主要风险 |
|---|---|---:|---|---|---|---|
| AKShare | [akfamily/akshare](https://github.com/akfamily/akshare) | 20240 / 3265 | MIT | 2026-06-11 updated，2026-05-27 pushed | 已完成第一优先 POC：ETF 日级历史、行情探测 | 上游接口可能受网页源变化影响；需做字段校验、重试和缓存 |
| AKTools | [akfamily/aktools](https://github.com/akfamily/aktools) | 1404 / 234 | MIT | 2026-06-10 updated，2025-10-29 pushed | AKShare HTTP 化参考，不优先作为核心依赖 | 多一层服务部署和运维，不适合当前最小 provider |
| TuShare | [waditu/tushare](https://github.com/waditu/tushare) | 15114 / 4437 | BSD-3-Clause | 2026-06-11 updated，2024-03-13 pushed | 有凭据/积分路径的补充 provider | token、积分、频率和服务条款需要显式配置，不适合作默认无凭据 provider |
| a-stock-data | [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) | 3861 / 781 | Apache-2.0 | 2026-06-03 pushed，最新 release v3.2.2 | 多数据源 Skill 和实现参考，不是可安装 Python 包 | 需要复制内嵌代码；没有稳定包 API、版本化调用边界或统一运行时错误契约 |
| mootdx | [mootdx/mootdx](https://github.com/mootdx/mootdx) | 1945 / 543 | MIT；README 附加非商业声明 | 2024-07-16 pushed，最新 release v0.11.7 | 通达信 TCP K 线技术候选 | 商业使用边界冲突；单次最多 800 条；国内网络更稳定；维护活跃度较低 |
| qstock | [tkfy920/qstock](https://github.com/tkfy920/qstock) | 1847 / 383 | MIT | 2026-06-10 updated，2025-03-16 pushed | 研究型备选，适合补充投研数据 | 依赖和接口边界需验证，优先级低于 AKShare |
| BaoStock 镜像 | [shimencaiji/baostock](https://github.com/shimencaiji/baostock) | 107 / 29 | 未声明 | 2026-06-09 updated，2019-10-25 pushed | 暂缓，仅作为历史参考 | GitHub 维护和许可不清晰，不符合高 star 整合包要求 |

Star、fork、license 和活跃度来自 GitHub 仓库元信息。GitHub 的 updated_at 可能由 issue、star 等事件触发，不能单独代表代码发布频率，因此同时记录 pushed_at。

## a-stock-data schema 验证结论

2026-06-12 对仓库结构、README、`SKILL.md` 和 PyPI 包索引完成复核：

- 仓库主体是 `README.md` 与约 82 KB 的 `SKILL.md`，不是带稳定 import API 的 Python 包；PyPI 没有名为 `a-stock-data` 的发行包。
- 安装方式是把 `SKILL.md` 放入 AI 助手的 skill 目录，再安装 `mootdx`、`requests`、`pandas`、`stockstats` 等底层依赖。
- 行情层实际组合了 mootdx、腾讯财经和百度 K 线。它提供的是可复制的代码片段与数据源经验，不是统一的、可版本锁定的 provider 运行时。
- 内嵌示例能覆盖 ETF、K 线和实时行情，但错误语义取决于各段代码：可能抛异常、返回空 DataFrame、返回上游错误 JSON，不能直接满足本项目的统一退出码和 stderr 契约。
- 项目更新记录本身也展示了直连上游接口会失效、改名或触发风控，因此其降级思路值得吸收，具体端点仍需逐个做契约测试。

决定：**不把 a-stock-data 自身接入 `history_command`，也不复制整份 Skill 进入仓库。** 后续只吸收其“多源优先级、限流、缓存、降级”的设计经验，并对底层数据源独立做许可、字段、单位和可用性验证。

## mootdx 技术验证结论

mootdx 的 `Quotes.bars()` 支持日 K 线，返回 DataFrame，使用 `start` 与 `offset` 分页，单次最多 800 条；`Quotes.k()` / `ohlc()` 提供日期区间封装。技术上可以转换成本项目的历史行情契约。

当前不新增 mootdx provider，原因是：

- 官方仓库采用 MIT License，但 README 同时明确声明项目只作学习交流、不得用于商业目的。两者存在使用边界冲突，生产接入前需要作者书面澄清或法务确认。
- PyPI 最新版 v0.11.7 发布于 2024-05-04，GitHub 最近一次 push 为 2024-07-16；可维护性需要纳入供应链风险评估。
- 它依赖通达信 TCP 行情服务器，官方相关资料和 a-stock-data 均提示国内网络更稳定，海外部署可能超时。
- 历史分页、ETF 覆盖、复权、成交量单位、服务器切换和空返回语义仍需真实样本验证，不能只凭示例进入回测主路径。

如果后续获得商业使用许可，可再做隔离的 guarded POC；在此之前不加入 `requirements.txt`，也不作为 AKShare 的自动降级源。

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
- 明确字段单位，尤其是把 AKShare / Eastmoney 按“手”返回的成交量转换为按“股”输出。
- 能通过 python cli\commands.py history probe --config ...。
- 缺字段、无数据、乱序日期、越界日期会被现有 DataManager / probe 拒绝。
- 不提交任何 token、cookie 或私有 provider 路径。

### POC 2：a-stock-data 输出 schema 验证

状态：已完成，结论为“不直接接入”。

保留成果：把数据源优先级、串行限流、缓存和降级纳入后续 adapter 设计；不把 Skill 当作稳定 provider 包。

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

1. 为 provider adapter 定义来源标识、重试、限流、缓存、降级顺序和可观测性，保持 `history_command` 输出契约不变。
2. 评估 TuShare 的 ETF 日线覆盖、token/积分要求、频率限制和服务条款，决定是否做第二个可选 provider。
3. 对任何候选先完成商业使用许可、字段单位、复权语义和空数据错误语义检查，再做 guarded live POC。
4. AKShare guarded live 验收继续保持显式启用，不把一次通过解释为长期可用性保证。
