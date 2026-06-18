# 研究/模拟版交付状态

本文定义当前阶段的交付口径。这里的“交付”指 ETF 量化助手的研究和模拟验证版，不包含 QMT/券商实盘、API/Web 控制台或生产 SLA。

## 交付结论

截至 2026-06-18，当前代码已达到 **研究/模拟验证版交付基线**。这表示仓库具备可重复的离线验收、策略与风控回归、状态恢复、历史 provider 接入演练和回测产物审计能力；不表示策略已经通过外部市场验证，也不表示系统可接入生产实盘。

## 当前能力

截至当前基线，项目已经具备：

- mock/simulator 阶段边界说明。
- grid / rotation 基础策略、风控、模拟成交和状态恢复。
- grid / rotation 回测、成交量参与率、滑点、最低佣金和生产可行性警告。
- 外部命令式历史 provider 契约、AKShare / TuShare 示例 provider 和 guarded live e2e 入口。
- provider 凭据门禁、重试、降级、缓存统计和文本/JSON 可观测性。
- CLI health / diagnose / report / history probe / history export / backtest 基础入口。
- 离线测试基线：`407 passed, 2 skipped`。

## 交付项状态

| 目标 | 交付内容 | 状态 |
|---|---|---|
| 交付口径 | 明确研究/模拟版能力、验收命令和非目标 | 完成 |
| 离线验收 | `scripts/verify_offline.py` 固定 compile / pytest / CLI smoke 顺序 | 完成 |
| provider 演练 | 无凭据配置模板与 missing env / backup / cache 演练 | 完成 |
| 回测产物 | 完整产物生成、schema、组合一致性和确定性复验 | 完成 |
| 文档收口 | README、architecture、testing 和 PRD gap 状态同步 | 完成 |

## 验证分层

当前内部回测引擎用于工程自验证，不应被单独解释为策略可生产。进入实盘预研前，应按三段式推进：

1. **内部自验证**：`scripts/verify_offline.py`、项目内 backtest、provider 契约、报告导出和状态恢复必须通过，用于验证本仓库的策略状态机、风控、执行模型和可观测性。
2. **公开回测平台交叉验证**：在聚宽、优矿、米筐等公开回测平台中至少选择一个复现关键策略假设，记录收益、调仓、成交、复权、交易日历、手续费和滑点模型差异。
3. **模拟盘 / 小资金实盘预研**：只有内部自验证通过，且公开平台差异可解释，才进入模拟盘或小资金实盘预研；该阶段还必须另行补齐真实订单状态机、kill switch 和运行审计。

公开回测平台用于验证策略结果和市场假设，内部回测用于验证本系统的工程链路。两者不能互相替代。

公开平台验证时使用 [公开回测平台交叉验证模板](public-backtest-validation.md)，必须显式记录复权、交易日历、费用、滑点、成交约束和差异解释。网格参数还需要证明扣除真实费用后仍有正期望，不接受依靠密集成交堆出的毛收益。

## 交付验收命令

离线交付至少需要通过：

```powershell
python scripts\verify_offline.py
```

只验收回测交付产物，默认使用临时目录并在完成后清理：

```powershell
python scripts\verify_backtest_artifacts.py
```

需要保留 grid / rotation 的完整产物和 SHA-256 manifest 时：

```powershell
python scripts\verify_backtest_artifacts.py --output-dir data\backtest-acceptance
```

该脚本会为每个策略生成 Markdown 报告及权益、组合、成交、持仓、拒单 CSV，校验固定字段、非空核心数据和组合总值一致性，并二次运行逐字节比较，避免把不可复现的产物交付出去。

该脚本等价于顺序执行：

```powershell
python -m compileall -q .
python -m pytest -q
python cli\commands.py health --no-state
python cli\commands.py diagnose --no-state
python cli\commands.py report --type daily --no-state
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy rotation
python scripts\verify_backtest_artifacts.py
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
