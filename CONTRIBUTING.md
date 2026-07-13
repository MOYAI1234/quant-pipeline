# 参与贡献

感谢你关注 quant-pipeline。项目当前定位是 ETF 策略研究与模拟验证，不接受将未经验证的策略直接描述为可实盘或可保证收益的改动。

## 开始之前

- Bug、文档问题和小型改进可以直接提交 Issue。
- 较大的新策略、数据源或架构改动，请先开 Issue 说明目标、数据来源、验证方式和维护成本。
- 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
- 不要提交 API key、token、cookie、个人账户信息、私有接口地址或无再分发授权的行情文件。

## 开发环境

需要 Python 3.10 或更高版本。克隆仓库后，在仓库根目录执行：

```shell
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1` 激活环境；macOS/Linux 使用 `source .venv/bin/activate`。

## 提交前验证

```shell
ruff check .
python scripts/verify_offline.py
```

Pull Request 必须保证：

- 新行为有对应测试，修复缺陷时包含回归测试。
- README 和 `docs/` 中的命令、字段和能力边界与实现一致。
- 策略研究记录说明数据来源、费用、滑点、复权和交易日历假设。
- 聚宽脚本依赖的平台注入全局对象只在 `examples/joinquant/` 中使用。
- 真实网络测试保持显式启用，默认离线测试不访问外部行情服务。

## Pull Request 说明

请在 PR 中写明：

1. 解决的问题和不在本次范围内的事项。
2. 关键实现选择及其风险。
3. 已运行的验证命令和结果。
4. 数据、第三方代码或策略思想的来源与许可证判断。

维护者可能要求拆分过大的 PR，或拒绝无法复现、数据来源不清、风险边界不完整的策略结论。
