# quant-pipeline

[![CI](https://github.com/MOYAI1234/quant-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/MOYAI1234/quant-pipeline/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

面向 ETF 策略研究的模块化量化流水线，覆盖数据适配、策略生成、风险检查、模拟执行、回测审计和监控报告。

An ETF strategy research pipeline with modular data adapters, risk controls, simulated execution, reproducible backtests, and audit-friendly reports.

> [!WARNING]
> 本项目仅用于研究、教学和软件工程验证，不构成投资建议。默认数据和执行环境均为 mock/simulator，不能直接用于实盘交易。任何策略结果都不代表未来收益。

## 项目定位

quant-pipeline 适合以下场景：

- 验证网格、轮动和 ETF 多资产策略的状态机与工程链路。
- 在统一的费用、滑点、成交量和交易日历约束下做本地 sanity check。
- 通过外部命令式 provider 接入 AKShare、TuShare 或自有历史行情服务。
- 导出权益、组合、成交、持仓和拒单数据，复核回测结果是否可重复。
- 将候选策略推进到公开回测平台交叉验证，再决定是否进入模拟盘预研。

当前能力边界：

| 模块 | 当前状态 |
|---|---|
| 数据 | 默认 mock；提供外部历史行情 provider 契约与 AKShare/TuShare 示例 |
| 策略 | 网格、ETF 轮动、双动量、防御型资产配置等研究实现 |
| 执行 | simulator 模拟成交，不连接券商 |
| 回测 | 用于工程自验证，包含费用、滑点、成交量限制和产物审计 |
| 实盘 | 不支持真实下单、订单回报、kill switch 或生产 SLA |

## 快速开始

### 1. 准备环境

需要 Python 3.10 或更高版本。所有命令都应在仓库根目录运行。

```shell
git clone https://github.com/MOYAI1234/quant-pipeline.git
cd quant-pipeline
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

安装运行依赖：

```shell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. 验证 CLI

```shell
python cli/commands.py health --no-state
```

默认输出应显示 `数据源状态: OK (mock)`。这表示本地工程链路可用，不代表已连接真实行情。

### 3. 运行内置回测

```shell
python cli/commands.py backtest --strategy grid
python cli/commands.py backtest --strategy rotation
```

两条命令会直接输出 Markdown 格式的回测摘要，不需要 API key 或网络行情。

## 开发与测试

安装开发依赖：

```shell
python -m pip install -r requirements-dev.txt
```

运行静态检查与完整离线验收：

```shell
ruff check .
python scripts/verify_offline.py
```

只运行测试：

```shell
python -m pytest -q
```

离线验收还会检查 CLI smoke、两类内置回测和回测产物的确定性。真实 AKShare/TuShare 网络测试默认跳过，启用方式见[真实历史数据验收](docs/live-data-validation.md)。

## 常用命令

| 目的 | 命令 |
|---|---|
| 查看 CLI | `python cli/commands.py --help` |
| 检查配置 | `python cli/commands.py config validate` |
| 启动前诊断 | `python cli/commands.py diagnose --no-state` |
| 查看数据源 | `python cli/commands.py health --no-state` |
| 生成日报 | `python cli/commands.py report --type daily --no-state` |
| 网格回测 | `python cli/commands.py backtest --strategy grid` |
| 轮动回测 | `python cli/commands.py backtest --strategy rotation` |
| 验证回测产物 | `python scripts/verify_backtest_artifacts.py` |

完整参数请使用对应命令的 `--help`，详细测试分层见[测试与验收指南](docs/testing.md)。

## 接入真实历史行情

仓库不保存 API key、token、cookie、私有接口地址或真实行情缓存。可复制示例配置到本地文件：

```shell
python cli/commands.py config init
```

或基于以下模板配置命令式 provider：

- [本地 provider 配置模板](examples/configs/history-providers.local.example.json)
- [AKShare 示例](examples/providers/akshare_history_provider.py)
- [TuShare 示例](examples/providers/tushare_history_provider.py)
- [历史行情 provider 契约](docs/history-provider-contract.md)
- [本地接入演练](docs/provider-local-drill.md)

AKShare 和 TuShare 都是可选依赖，不会随 `requirements.txt` 安装。真实数据的授权、频率限制、复权口径和再分发条件由使用者自行核对。

## 目录结构

```text
adapters/       外部数据和知识服务适配层
analysis/       宏观、ETF 和新闻分析模块
backtest/       回测 runner、执行模型和交易日历
cli/            命令行入口
config/         默认配置、校验和日志配置
data/           数据管理、缓存和数据契约
docs/           架构、验收、provider 与策略研究文档
examples/       最小示例、provider 和聚宽脚本
execution/      模拟执行器和订单管理
monitor/        运行指标、告警和报告
persistence/    状态快照与恢复
research/       ETF 候选策略和研究逻辑
risk/           ETF 质量、仓位和止损风控
scripts/        验收、回测、筛选和数据转换脚本
strategy/       网格与轮动策略实现
tests/          单元测试和集成测试
```

## 研究与验证原则

- 本地回测用于验证工程链路，不单独证明策略有效。
- 策略进入模拟盘前，应在聚宽、优矿或米筐等公开平台交叉验证。
- 数据来源、复权、交易日历、手续费、滑点和撮合差异必须可解释。
- 真实行情文件和受许可限制的数据不得提交到仓库。
- 实盘能力必须另行补齐订单状态机、异常停机、审计和 kill switch。

## 文档

- [架构说明](docs/architecture.md)
- [研究/模拟版交付状态](docs/release-readiness.md)
- [测试与验收指南](docs/testing.md)
- [策略研究工作流](docs/strategy-research-workflow.md)
- [稳健 ETF 策略研究台账](docs/strategy-lab/README.md)
- [策略候选索引](docs/strategy-candidates/README.md)
- [公开回测平台交叉验证](docs/public-backtest-validation.md)
- [数据源选型矩阵](docs/data-source-provider-evaluation.md)
- [聚宽复现脚本说明](examples/joinquant/README.md)

## 参与贡献

提交 Issue 或 Pull Request 前，请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中披露漏洞或凭据。

## 许可证

本项目使用 [MIT License](LICENSE)。第三方数据、平台和服务仍受各自条款约束。
