# 安全策略

## 支持范围

安全修复以默认分支 `master` 的最新版本为准。研究分支、历史提交和第三方行情服务不单独提供安全维护承诺。

## 报告安全问题

请优先使用 GitHub 仓库 **Security → Report a vulnerability** 提交私密漏洞报告：

https://github.com/MOYAI1234/quant-pipeline/security/advisories/new

请勿在公开 Issue、Discussion、Pull Request 或日志中披露漏洞细节、真实凭据、账户信息和私有行情数据。

报告中建议包含：

- 受影响的提交或版本。
- 可复现的最小步骤。
- 可能影响的数据、权限或执行路径。
- 已知缓解方式。

维护者确认问题后会通过私密安全公告协调修复与披露。不要在未获得许可的情况下访问他人账户、扩大测试范围或保留测试中接触到的数据。

## 项目边界

本项目默认运行于 mock/simulator 环境，不提供真实券商交易安全保证。第三方 provider、API、SDK 和公开回测平台的安全问题应同时报告给对应服务提供方。
