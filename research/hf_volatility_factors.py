"""ETF 高频波动率因子研究模块 (FACTOR-107 ~ 109)。

出处: 中信建投证券《高频流动性与波动率因子再构建》(2025-10)；
波动率估计器经典文献:
  - Parkinson (1980): sigma_P = sqrt( 1/(4*ln2) * mean( ln(H/L)^2 ) )
  - Garman & Klass (1980): sigma_GK = sqrt( 0.5*mean(ln(H/L)^2)
        - (2*ln2 - 1) * mean(ln(C/O)^2) )
  - Yang & Zhang (2000): 组合隔夜跳空与日内 open-to-close 波动，对跳空稳健

与已有 SHARPE 因子(用 close 日收益算波动)的区别: 高频估计器利用日内
H/L/O/C 信息，波动率估计更精确、对价格路径信息利用更充分。
2025 中信建投实测: garman_klass_vol 增强因子多空年化 33.3%、夏普 3.39。

因子方向（ETF 轮动做多语境）: factor = momentum_60d / sigma_hf_20d，
即"高频波动率调整动量"——同等动量下，日内路径越平稳(低 H/L 波动)越优先，
对应 low-vol anomaly 与 2025 研报"低波优先"结论。

数据: tushare fund_daily 的 open/high/low/close 列（scripts/fetch_etf_ohlcv_tushare.py）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class HfVolConfig:
    """高频波动率调整动量因子配置"""
    momentum_window: int = 60
    vol_window: int = 20           # 波动率估计窗口
    estimator: str = "gk"          # parkinson / gk / yz
    min_history_days: int = 61
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.momentum_window + 1, self.vol_window + 1, self.min_history_days)


def _to_series(bar: dict, key: str) -> list[float]:
    raw = bar.get(key, [])
    if isinstance(raw, str):
        raw = [float(p) for p in raw.split("|") if p]
    return [float(p) for p in raw]


def _parkinson_vol(highs: list[float], lows: list[float]) -> float:
    """Parkinson (1980) 日内高低点波动率。"""
    n = len(highs)
    if n < 2:
        return 0.0
    vals = []
    for h, lo in zip(highs, lows):
        if h > 0 and lo > 0 and h >= lo:
            r = math.log(h / lo)
            vals.append(r * r)
    if not vals:
        return 0.0
    return math.sqrt(sum(vals) / len(vals) / (4.0 * math.log(2.0)))


def _garman_klass_vol(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float]
) -> float:
    """Garman-Klass (1980) 日内高低开收波动率。"""
    n = len(opens)
    if n < 2:
        return 0.0
    hl = 0.0
    co = 0.0
    cnt = 0
    for o, h, lo, c in zip(opens, highs, lows, closes):
        if min(o, h, lo, c) <= 0 or h < lo:
            continue
        hl += math.log(h / lo) ** 2
        co += math.log(c / o) ** 2
        cnt += 1
    if cnt == 0:
        return 0.0
    # 有限样本下方差可能为负（日内 OC 波动相对 HL 较大时），取 max(0,·) 防止 sqrt 崩溃
    return math.sqrt(max(0.0, 0.5 * hl / cnt - (2.0 * math.log(2.0) - 1.0) * co / cnt))


def _yang_zhang_vol(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float]
) -> float:
    """Yang-Zhang (2000) 波动率：隔夜 + 日内分解，对跳空稳健。"""
    n = len(opens)
    if n < 4:
        return 0.0
    oo = []  # 隔夜跳空收益 (O_t - C_{t-1})
    oc = []  # 日内收益 (C_t - O_t)
    for i in range(1, n):
        if opens[i] <= 0 or closes[i - 1] <= 0 or opens[i - 1] <= 0:
            continue
        oo.append(math.log(opens[i] / closes[i - 1]))
        oc.append(math.log(closes[i] / opens[i]))
    if len(oo) < 3 or len(oc) < 3:
        return 0.0

    def var(xs: list[float]) -> float:
        m = sum(xs) / len(xs)
        return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)

    var_oo = var(oo)
    var_oc = var(oc)
    var_hl = 0.0
    cnt = 0
    for i in range(1, n):
        h, lo, c_prev, o = highs[i], lows[i], closes[i - 1], opens[i]
        if min(h, lo, c_prev, o) <= 0 or h < lo:
            continue
        var_hl += math.log(h / lo) ** 2
        cnt += 1
    if cnt < 3:
        return 0.0
    var_hl = var_hl / cnt

    k = 0.34 / (1.34 + (len(oo) + 1) / (len(oo) - 1)) if len(oo) > 1 else 0.34
    # Yang-Zhang: sigma^2 = var_oo + k*var_oc + (1-k)*var_hl（zhang 变体）
    return math.sqrt(max(0.0, var_oo + k * var_oc + (1.0 - k) * var_hl))


def calc_hf_vol_momentum(
    symbol: str,
    bar: dict,
    config: HfVolConfig,
) -> tuple[dict | None, str | None]:
    """高频波动率调整动量因子。

    factor_value = momentum_60d / sigma_hf_20d
    sigma_hf 用 Parkinson / Garman-Klass / Yang-Zhang 之一。
    """
    closes = _to_series(bar, "prices")
    if not closes:
        return None, 'invalid_prices'
    closes = [c for c in closes if c > 0]
    if len(closes) < config.required_prices:
        return None, f'insufficient_prices len={len(closes)} need={config.required_prices}'

    # 高频估计器需要 OHLC 序列（单日 bar 只带当日 OHLC 时用滚动窗口近似：
    # 因子引擎逐 bar 调用，bar 若只含当日 OHLC 则无法滚动 ——
    # 这里支持两种形态: (1) bar 含 ohlc 序列(pipe 串), (2) 仅当日 OHLC(单点)。
    # 单点形态下退化窗口 = 1 日估计不稳，故要求序列形态。
    opens = _to_series(bar, "opens")
    highs = _to_series(bar, "highs")
    lows = _to_series(bar, "lows")
    use_hf = (
        len(opens) >= config.vol_window
        and len(highs) >= config.vol_window
        and len(lows) >= config.vol_window
    )

    if use_hf:
        o = opens[-config.vol_window:]
        h = highs[-config.vol_window:]
        lo = lows[-config.vol_window:]
        c = closes[-config.vol_window:]
        if config.estimator == "parkinson":
            vol = _parkinson_vol(h, lo)
        elif config.estimator == "yz":
            vol = _yang_zhang_vol(o, h, lo, c)
        else:
            vol = _garman_klass_vol(o, h, lo, c)
    else:
        # 退化: close 日收益波动率（与 SHARPE 一致，供对照）
        win = closes[-config.vol_window - 1:]
        rets = [b / a - 1.0 for a, b in zip(win, win[1:]) if a > 0]
        vol = _annualized_volatility(rets) if len(rets) >= 5 else 0.0

    momentum = closes[-1] / closes[-config.momentum_window - 1] - 1.0
    if not math.isfinite(momentum):
        return None, 'nan_momentum'
    if vol <= 0:
        return None, 'zero_vol'

    factor_value = momentum / vol

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "momentum": momentum,
        "volatility": vol,
        "estimator": config.estimator,
        "amount": bar.get("amount"),
    }, None


def _annualized_volatility(daily_returns: list[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)
