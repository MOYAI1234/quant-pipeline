# 真实历史数据验收

本文说明如何显式运行 AKShare / TuShare 历史行情 guarded e2e。这些测试默认跳过，不属于离线 CI 的强制依赖。

## 验收范围

测试会走完整链路：

1. CLI `history probe`
2. `DataManager.get_etf_history()`
3. `MXDataAdapter.history_command` / `history_providers`
4. `examples/providers/akshare_history_provider.py` 或 `examples/providers/tushare_history_provider.py`
5. AKShare `fund_etf_hist_em` 或 TuShare `fund_daily`

测试只校验返回数据可用、日期位于请求区间内，并复用现有数据契约校验。它不会保存真实行情文件，也不会提交 token、cookie 或本地配置。

AKShare 单标的 live test 通过后，如需验收 rotation 多标的导出，建议使用 `history export-rotation --symbol-delay-seconds 30`。公开网页源可能在连续请求后短时断开连接；节流可以降低触发概率，但不能被解释为可用性 SLA。

## 运行方式

安装可选依赖：

```powershell
python -m pip install akshare
```

显式启用 live test：

```powershell
$env:RUN_AKSHARE_LIVE = '1'
python -m pytest tests\test_akshare_history_provider_live.py -q
Remove-Item Env:RUN_AKSHARE_LIVE
```

默认全量测试会显示该用例为 skipped：

```powershell
python -m pytest -q
```

TuShare：

```powershell
python -m pip install tushare
$env:TUSHARE_TOKEN = '<本地 token>'
$env:TUSHARE_API_URL = '<可选 TuShare 反代地址>'
$env:RUN_TUSHARE_LIVE = '1'
python -m pytest tests\test_tushare_history_provider_live.py -q
Remove-Item Env:RUN_TUSHARE_LIVE
Remove-Item Env:TUSHARE_API_URL
Remove-Item Env:TUSHARE_TOKEN
```

`TUSHARE_API_URL` 是可选项。设置后，示例 provider 会在创建 TuShare SDK client 后覆盖 `pro._DataApi__http_url`，用于本地反代验收。不要把 token 或私有反代地址写入配置文件、命令参数或提交记录。若反代限速为每分钟 100 次，批量导出仍建议显式设置请求间隔，例如 `history export-rotation --symbol-delay-seconds 1`；如果存在 AKShare 降级路径，可使用更保守的间隔。

## 失败解释

- 缺少 `RUN_AKSHARE_LIVE=1`：正常跳过，避免 CI 意外访问网络。
- 缺少 `akshare`：启用 live test 后会失败，并提示安装可选依赖，避免把未执行误判为验收通过。
- 缺少 `RUN_TUSHARE_LIVE=1`：正常跳过，避免 CI 意外访问网络。
- 缺少 `tushare`、`TUSHARE_TOKEN`、账户积分、接口权限或反代可用性：启用 TuShare live test 后会明确失败，不回退为假成功。
- provider 非零退出、超时或返回非法数据：测试失败，并展示 CLI/provider 的 stderr。
- 上游网页源临时不可用：属于真实数据源可用性问题，不应通过放宽数据契约来掩盖。

真实环境验收结果会受 provider 包版本、上游服务、账户权限和网络状态影响。生产接入仍需要重试、缓存、监控和备选 provider，不能把一次 live test 通过视为长期 SLA。
