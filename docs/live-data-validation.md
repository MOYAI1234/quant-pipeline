# 真实历史数据验收

本文说明如何显式运行 AKShare 历史行情 guarded e2e。该测试默认跳过，不属于离线 CI 的强制依赖。

## 验收范围

测试会走完整链路：

1. CLI `history probe`
2. `DataManager.get_etf_history()`
3. `MXDataAdapter.history_command`
4. `examples/providers/akshare_history_provider.py`
5. AKShare `fund_etf_hist_em`

测试只校验返回数据可用、日期位于请求区间内，并复用现有数据契约校验。它不会保存真实行情文件，也不会提交 token、cookie 或本地配置。

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

## 失败解释

- 缺少 `RUN_AKSHARE_LIVE=1`：正常跳过，避免 CI 意外访问网络。
- 缺少 `akshare`：启用 live test 后会失败，并提示安装可选依赖，避免把未执行误判为验收通过。
- provider 非零退出、超时或返回非法数据：测试失败，并展示 CLI/provider 的 stderr。
- 上游网页源临时不可用：属于真实数据源可用性问题，不应通过放宽数据契约来掩盖。

真实环境验收结果会受 AKShare 版本、上游 Eastmoney 页面和网络状态影响。生产接入仍需要重试、缓存、监控和备选 provider，不能把一次 live test 通过视为长期 SLA。
