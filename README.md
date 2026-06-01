# quant-pipeline

ETF 量化助手 Pipeline，目标是把数据适配、策略生成、风控检查、模拟执行、监控报告和后续回测/实盘接口组织成一条可迭代的交易研究流水线。

## 当前阶段

当前代码处于 **mock 数据 + simulator 模拟交易** 阶段，适合用于验证策略状态机、执行器、风控链路和后续回测框架，不是生产实盘系统。

重要边界：

- `adapters/` 中的 `mx-data`、`mx-xuangu`、`mx-search`、`jason-kb` 适配器目前仍是占位实现，未接真实外部服务。
- `execution/Simulator` 是简化成交模型，支持整手、手续费、均价、持仓和市值估算，但不包含真实撮合、滑点、订单状态同步。
- 策略状态目前以内存为主，重启后不会自动恢复网格 ledger、轮动 pending 状态或成交流水。
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

启动网格策略模拟循环：

```powershell
python cli\commands.py start --strategy grid --symbol 510300
```

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

- `Simulator` 买入、卖出、均价、部分卖出和市值估算
- `GridStrategy` 多格买入、同格防重复、卖出、止损后 ledger 重置
- `RotationStrategy` 首次调仓、卖旧买新、失败 pending 清理和重试
- `QuantPipeline.run_once()` 单轮策略执行与监控更新

## 下一步路线

优先级从高到低：

1. 补强测试和主循环可测性。
2. 明确 adapter 的 mock/real 模式和数据契约。
3. 实现历史行情驱动的回测引擎。
4. 持久化账户、成交和策略状态。
5. 完善监控报告和告警闭环。
6. 在模拟和回测稳定后，再预研 QMT/实盘执行。

实盘相关能力必须在显式配置、充分测试和状态可恢复后再启用。
