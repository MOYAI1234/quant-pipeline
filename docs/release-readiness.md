# 研究/模拟版交付清单

本文定义当前阶段的交付口径。这里的“交付”指 ETF 量化助手的研究和模拟验证版，不包含 QMT/券商实盘、API/Web 控制台或生产 SLA。

## 当前判断

截至当前基线，项目已经具备：

- mock/simulator 阶段边界说明。
- grid / rotation 基础策略、风控、模拟成交和状态恢复。
- grid / rotation 回测、成交量参与率、滑点、最低佣金和生产可行性警告。
- 外部命令式历史 provider 契约、AKShare / TuShare 示例 provider 和 guarded live e2e 入口。
- provider 凭据门禁、重试、降级、缓存统计和文本/JSON 可观测性。
- CLI health / diagnose / report / history probe / history export / backtest 基础入口。
- 离线测试基线：`396 passed, 2 skipped`。

## 剩余 PR 估算

完成研究/模拟版交付预计还需要 **4-6 个小 PR**。

| 序号 | 目标 | 交付内容 | 预计 PR |
|---|---|---|---:|
| 1 | 交付口径收口 | 维护本清单，明确当前交付边界、验收命令和非目标 | 1 |
| 2 | 离线验收脚本 | 增加一键本地验收命令或脚本，固定 compile / pytest / CLI smoke 顺序 | 1 |
| 3 | provider 接入演练 | 增加不含凭据的 provider 配置模板和本地演练说明，覆盖 missing env / backup / cache 输出 | 1 |
| 4 | 回测产物验收 | 增强回测导出文档或测试，确保报告、权益、组合、成交、拒单 CSV 可复现 | 1 |
| 5 | 最终文档收口 | README、architecture、testing 和 PRD gap 状态同步到交付版 | 1 |
| 6 | 预留修复 | 处理 review 或验收中暴露的小缺口 | 0-1 |

如果只做“代码可跑 + 文档清楚”的轻量交付，偏向 4 个 PR；如果把 provider 接入演练和回测产物验收写得更扎实，偏向 6 个 PR。

## 交付验收命令

离线交付至少需要通过：

```powershell
python -m compileall -q .
python -m pytest -q
python cli\commands.py health --no-state
python cli\commands.py diagnose --no-state
python cli\commands.py report --type daily --no-state
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy rotation
python cli\commands.py history probe --help
python cli\commands.py history export-grid --help
python cli\commands.py history export-rotation --help
```

显式启用的真实数据验收仍是可选项：

```powershell
$env:RUN_AKSHARE_LIVE = '1'
python -m pytest tests\test_akshare_history_provider_live.py -q
Remove-Item Env:RUN_AKSHARE_LIVE

$env:TUSHARE_TOKEN = '<本地 token>'
$env:RUN_TUSHARE_LIVE = '1'
python -m pytest tests\test_tushare_history_provider_live.py -q
Remove-Item Env:RUN_TUSHARE_LIVE
Remove-Item Env:TUSHARE_TOKEN
```

## 非目标

以下内容不属于本轮研究/模拟版交付：

- QMT / 券商实盘下单。
- 真实订单回报状态机。
- Web / API 控制台。
- 外部通知通道。
- 真实行情服务 SLA。
- 高频或密集网格生产策略。

这些能力需要在真实数据源、状态恢复、风控门禁和 kill switch 都稳定后，单独进入实盘预研阶段。
