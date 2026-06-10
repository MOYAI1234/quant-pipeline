# 测试与验收指南

本文档说明 `quant-pipeline` 当前 mock/simulator 阶段的测试入口、覆盖范围和交付验收口径。

## 基础命令

完整测试：

```powershell
python -m pytest -q
```

语法检查：

```powershell
python -m compileall -q .
```

CLI smoke：

```powershell
python cli\commands.py --help
python cli\commands.py health
python cli\commands.py config validate
python cli\commands.py report --type daily
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy rotation
python cli\commands.py history export-grid --help
python cli\commands.py history export-rotation --help
```

当前基线：`pytest` 应通过 277 个测试。

## 分层测试

### 数据适配与契约

相关测试：

```powershell
python -m pytest tests\test_adapters.py tests\test_data_manager_contracts.py tests\test_data_cache.py tests\test_cli_health.py -q
```

验收重点：

- adapter 必须明确 `mode=mock|real`。
- `mock` 模式可用于链路验证，但不能伪装成真实行情。
- `real` 模式未实现时必须明确不可用，并抛出服务不可用错误。
- `DataManager` 必须校验实时行情、净值和历史行情的字段、数值类型、非负单位和可选时效。

### 策略、风控与模拟执行

相关测试：

```powershell
python -m pytest tests\test_simulator.py tests\test_e2e_grid.py tests\test_rotation_strategy.py tests\test_risk_manager.py -q
```

验收重点：

- `Simulator` 支持买入、卖出、均价、手续费、部分卖出和市值估算。
- `GridStrategy` 支持多格买入、同格防重复、卖出和止损后 ledger 重置。
- `RotationStrategy` 支持首次调仓、卖旧买新、失败 pending 清理和重试。
- `RiskManager` 覆盖仓位、ETF 质量、固定止损、单笔止损、跟踪止损和组合亏损告警边界。

### 回测

相关测试：

```powershell
python -m pytest tests\test_backtest_runner.py tests\test_backtest_history_adapter.py tests\test_trading_calendar.py -q
```

验收重点：

- grid 和 rotation 都能跑内置历史样例并生成 Markdown 报告。
- grid 支持历史 bar list/CSV；rotation 支持 JSON snapshot 和 CSV 长表。
- 回测必须校验历史日期/盘中时间严格递增、OHLC 合法性、价格、成交量和成交额。
- `BacktestExecutionModel` 统一处理滑点、成交量参与率限制、同一 bar 成交量占用和成交前拒单归因。
- 导出文件包括权益曲线、组合快照、成交明细、持仓明细和拒单明细。
- `history export-grid/export-rotation` 能把本地 JSON 或 `DataManager.get_etf_history()` 返回值转换为回测 CSV。

### 状态持久化与主循环

相关测试：

```powershell
python -m pytest tests\test_state_persistence.py tests\test_pipeline_run_once.py tests\test_cli_state.py -q
```

验收重点：

- `JsonStateStore` 能保存和恢复账户、策略状态、内部订单状态和运行 metadata。
- 旧版无顶层 `version` 状态可迁移到 v1。
- `QuantPipeline.run_once()` 能用 mock data 跑一个 tick，并更新订单状态、监控指标和 `last_market_time_by_symbol`。

### 报告和告警

相关测试：

```powershell
python -m pytest tests\test_report_health.py tests\test_alerts.py tests\test_cli_alerts.py tests\test_cli_config.py -q
```

验收重点：

- 日报/周报包含组合、交易、风险、数据源健康状态和告警事件摘要。
- `AlertManager` 支持结构化事件、内存历史和可选 JSONL 文件输出。
- CLI `alerts` 能读取 JSONL 并输出文本或 JSON。

## CLI 回测验收样例

grid：

```powershell
python cli\commands.py backtest --strategy grid
python cli\commands.py backtest --strategy grid --equity-output data\grid-equity.csv
python cli\commands.py backtest --strategy grid --portfolio-output data\grid-portfolio.csv
python cli\commands.py backtest --strategy grid --trades-output data\grid-trades.csv
python cli\commands.py backtest --strategy grid --positions-output data\grid-positions.csv
python cli\commands.py backtest --strategy grid --rejections-output data\grid-rejections.csv
```

rotation：

```powershell
python cli\commands.py backtest --strategy rotation
python cli\commands.py backtest --strategy rotation --equity-output data\rotation-equity.csv
python cli\commands.py backtest --strategy rotation --portfolio-output data\rotation-portfolio.csv
python cli\commands.py backtest --strategy rotation --trades-output data\rotation-trades.csv
python cli\commands.py backtest --strategy rotation --positions-output data\rotation-positions.csv
python cli\commands.py backtest --strategy rotation --rejections-output data\rotation-rejections.csv
```

## 历史数据转换验收

本地 JSON 到 grid CSV：

```powershell
python cli\commands.py history export-grid --input-json path\to\grid-history.json --output data\grid-history.csv
python cli\commands.py backtest --strategy grid --history data\grid-history.csv
```

本地 JSON 到 rotation CSV：

```powershell
python cli\commands.py history export-rotation --input-json path\to\rotation-histories.json --lookback 3 --output data\rotation-history.csv
python cli\commands.py backtest --strategy rotation --history data\rotation-history.csv
```

未提供 `--input-json` 时，`history export-*` 会调用 `DataManager.get_etf_history()`，并且必须同时指定 `--start-date` 和 `--end-date`：

```powershell
python cli\commands.py history export-grid --symbol 510300 --start-date 2026-01-01 --end-date 2026-01-31 --output data\grid-history.csv
python cli\commands.py history export-rotation --symbols 510300,159915 --start-date 2026-01-01 --end-date 2026-01-31 --lookback 3 --output data\rotation-history.csv
```

当前默认 adapter 是 mock/空历史，真实数据接入前该路径只用于验证调用边界，不代表真实可用数据。

## 交付边界

当前交付目标是研究和模拟验证：

- 可以验证策略状态机、风控边界、模拟成交、状态恢复、报告和回测导出。
- 不提供真实行情、真实筛选、真实新闻、真实券商撮合或 QMT 报单。
- 不把 mock 空结果解释为真实市场结论。
- 实盘相关能力必须等真实数据、订单状态机、持久化迁移和 kill switch 都完成后再启用。
