"""ETF 新因子研究模块 (FACTOR-101 ~ 106)。

第一批 (FACTOR-101 ~ 103, 经典学术/社区出处, 2026-07-31):

  FACTOR-101: 52WH  (52 周高点距离)
      出处: George & Hwang (2004), Journal of Finance 59(5).
  FACTOR-102: ER    (Kaufman 效率比 × 方向)
      出处: Kaufman (1995), Smarter Trading.
  FACTOR-103: DDM   (下行偏差调整动量)
      出处: Sortino & van der Meer (1991), Journal of Portfolio Management.

第二批 (FACTOR-104 ~ 106, 2010s 后的现代因子, 2026-07-31):

  FACTOR-104: IDMOM (信息离散度调整动量)
      出处: Da, Gurun & Warachka (2014), "Frog in the Pan: Continuous
            Information and Momentum", Review of Financial Studies 27(7).
      逻辑: ID = sign(PRET) * (%neg - %pos) ∈ [-1, 1]。
            ID < 0 = 信息连续释放(温水煮青蛙, 投资者反应不足) -> 动量更强;
            ID > 0 = 信息一次性跳跃(离散) -> 动量弱甚至反转。
            实证: 形成期累计收益相近时, 动量从连续组的 5.94%/月 单调下降到
            离散组的 -2.07%/月。factor = momentum * (1 - ID)，
            连续信息放大动量、离散信息压缩动量 —— 动量质量维度。
            与纯动量区分: 只看收益路径的连续/离散结构, 不看累计幅度。

  FACTOR-105: HURST (分形趋势持续性)
      出处: Mandelbrot 分形市场假说; R/S 分析 (Hurst 1951), 量化实践
            2010s-2020s 大量应用。
      逻辑: H>0.5 趋势持续(动量有效), H<0.5 均值回归(反转有效)。
            factor = momentum * (H - 0.5) * 2 —— 用趋势持续性缩放动量。
            与纯动量区分: 动量假定趋势恒定, HURST 度量趋势的"粘性"。

  FACTOR-106: RKURT (已实现峰度/尾部风险惩罚动量)
      出处: Amaya, Christoffersen, Jacobs & Vasquez (2015),
            "Does realized skewness predict the cross-section of equity
            returns?", Journal of Financial Economics 118(1)。
      逻辑: RKURT = N * Σr^4 / (Σr^2)^2, 度量窗口内收益分布的尾部厚度。
            高峰度 = 尾部事件多(暴涨暴跌) = 持有风险高, 实证负向。
            factor = momentum / (1 + RKURT/5) —— 尾部风险高的动量被压缩。
            与已有因子区分: 覆盖四阶矩(尾部风险), 已有池无此维度。

  [暂缓] FACTOR-103': LIQ-IMP (Amihud 流动性改善)
      出处: Amihud (2002), JFM 5, 31-56。
      未实现原因: 因子契约只提供单日 bar(当日 amount), 无法还原历史
      成交额序列。待数据契约升级后实现。

每个因子遵循 calc_fn(symbol, bar, config) -> (factor_dict|None, err|None)
契约，供 scripts/backtest_etf_multi_factor.py 的通用回测引擎调用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# --- Factor Configs ---

@dataclass(frozen=True)
class FiftyTwoWeekHighConfig:
    """52 周高点距离因子配置"""
    high_window: int = 252      # A 股一年约 244 交易日，252 保守覆盖
    high_threshold: float = 0.0  # ratio >= 阈值才产生正信号 (0.0=恒持有)
    min_history_days: int = 253
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.high_window, self.min_history_days)


@dataclass(frozen=True)
class EfficiencyRatioConfig:
    """Kaufman 效率比因子配置"""
    er_window: int = 60
    min_history_days: int = 61
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.er_window + 1, self.min_history_days)


@dataclass(frozen=True)
class DownsideDevConfig:
    """下行偏差调整动量因子配置"""
    momentum_window: int = 60
    min_history_days: int = 61
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.momentum_window + 1, self.min_history_days)


@dataclass(frozen=True)
class InfoDiscretenessConfig:
    """信息离散度调整动量因子配置 (Da, Gurun & Warachka 2014)"""
    momentum_window: int = 60       # 形成期窗口（与已有动量一致，便于对比）
    min_history_days: int = 61
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.momentum_window + 1, self.min_history_days)


@dataclass(frozen=True)
class HurstConfig:
    """分形趋势因子配置 (R/S 分析)"""
    window: int = 120               # R/S 分析窗口（需 >= 80 才稳定）
    momentum_window: int = 60
    min_history_days: int = 121
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.window, self.momentum_window + 1, self.min_history_days)


@dataclass(frozen=True)
class RealizedKurtConfig:
    """已实现峰度/尾部风险惩罚因子配置 (Amaya et al. 2015)"""
    kurt_window: int = 20
    momentum_window: int = 60
    min_history_days: int = 61
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.kurt_window + 1, self.momentum_window + 1, self.min_history_days)


@dataclass(frozen=True)
class Combined52WHIDConfig:
    """52WH × IDMOM 组合因子配置。

    选股主体 = 52 周高点距离（George & Hwang 2004），
    质量调节 = 信息离散度 (1 - ID)（Da, Gurun & Warachka 2014）。
    factor_value = 52wh_ratio * (1 - ID)：
      - 连续信息(ID<0) 放大接近高点信号（温水煮青蛙，动量强）
      - 离散信息(ID>0) 压缩甚至清零（一次性跳跃，动量弱）
    可选离散过滤: id_filter > 0 时, ID > id_filter 的标的直接排除(0 分)。
    """
    high_window: int = 252
    id_window: int = 60            # 与动量窗口一致
    min_history_days: int = 253
    max_holdings: int = 2
    id_filter: float = 0.0         # >0 时启用: ID 高于此值的标的排除
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.high_window, self.id_window + 1, self.min_history_days)


# --- Factor Computation ---

def _to_prices(bar: dict) -> list[float] | None:
    prices = bar.get("prices", [])
    try:
        if isinstance(prices, str):
            prices = [float(p) for p in prices.split("|") if p]
        else:
            prices = list(prices)
        if not prices:
            return None
    except (ValueError, TypeError):
        return None
    if any(p <= 0 or not math.isfinite(p) for p in prices):
        return None
    return prices


def calc_52_week_high(
    symbol: str,
    bar: dict,
    config: FiftyTwoWeekHighConfig,
) -> tuple[dict | None, str | None]:
    """52 周高点距离因子。

    factor_value = close / max(close[-high_window:])
    值域 (0, 1]，越接近 1 说明价格越贴近 52 周高点，信号越强。
    George & Hwang (2004): 接近 52 周高点 -> 后续收益更强。
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    window = min(config.high_window, len(prices) - 1)
    high = max(prices[-window:])
    if high <= 0:
        return None, 'invalid_high'

    ratio = prices[-1] / high
    if not math.isfinite(ratio):
        return None, 'nan_ratio'

    distance = ratio - 1.0
    mom_20d = prices[-1] / prices[-21] - 1.0 if len(prices) >= 21 else 0.0

    # 阈值门控: factor_value = ratio - threshold，
    # 只有贴近 52 周高点(ratio >= threshold)的标的正信号才生效，
    # 市场整体远离高点(回调期)时自然空仓，见 George & Hwang (2004)。
    factor_value = ratio - config.high_threshold

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "ratio": ratio,
        "distance_from_high": distance,
        "high_window": window,
        "high_threshold": config.high_threshold,
        "momentum_20d": mom_20d,
        "amount": bar.get("amount"),
    }, None


def calc_efficiency_ratio(
    symbol: str,
    bar: dict,
    config: EfficiencyRatioConfig,
) -> tuple[dict | None, str | None]:
    """Kaufman 效率比 × 动量方向因子。

    ER = |P(t) - P(t-n)| / sum(|P(i) - P(i-1)| for i in [t-n+1, t])
    factor_value = ER * (P(t)/P(t-n) - 1)
    高效上涨 -> 高分；高效下跌 -> 负分；震荡路径 -> 接近 0。
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    n = config.er_window
    win = prices[-n - 1:]  # n+1 个价格 -> n 段变化
    net_move = abs(win[-1] - win[0])
    path = sum(abs(b - a) for a, b in zip(win, win[1:]))
    if path <= 0:
        return None, 'flat_path'

    er = net_move / path
    direction = win[-1] / win[0] - 1.0 if win[0] > 0 else 0.0
    factor_value = er * direction

    daily_returns = [b / a - 1.0 for a, b in zip(win, win[1:]) if a > 0]
    vol = _annualized_volatility(daily_returns) if len(daily_returns) >= 5 else 0.0

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "efficiency_ratio": er,
        "net_move": net_move,
        "path_length": path,
        "momentum": direction,
        "volatility": vol,
        "amount": bar.get("amount"),
    }, None


def calc_downside_dev(
    symbol: str,
    bar: dict,
    config: DownsideDevConfig,
) -> tuple[dict | None, str | None]:
    """下行偏差调整动量因子。

    momentum = P(t)/P(t-n) - 1
    downside_dev = sqrt( mean( min(r_d - MAR, 0)^2 ) ) * sqrt(252), MAR=0
    factor_value = momentum / downside_dev
    只有下跌日的波动被惩罚；上涨日的剧烈波动不惩罚。
    与 SHARPE(总波动) 的关键区别，见 Sortino & van der Meer (1991)。
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    n = config.momentum_window
    win = prices[-n - 1:]
    momentum = win[-1] / win[0] - 1.0
    if not math.isfinite(momentum):
        return None, 'nan_momentum'

    daily_returns = [b / a - 1.0 for a, b in zip(win, win[1:]) if a > 0]
    if len(daily_returns) < 5:
        return None, 'insufficient_returns'

    downside = [r for r in daily_returns if r < 0.0]
    if not downside:
        # 窗口内无下跌日：下行偏差为 0，动量>0 给满分信号
        dd = 0.0
    else:
        mean_sq = sum(r * r for r in downside) / len(daily_returns)
        dd = math.sqrt(mean_sq) * math.sqrt(252)

    if dd <= 0:
        factor_value = momentum if momentum > 0 else 0.0
    else:
        factor_value = momentum / dd

    total_vol = _annualized_volatility(daily_returns)

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "momentum": momentum,
        "downside_deviation": dd,
        "downside_days": len(downside),
        "total_volatility": total_vol,
        "amount": bar.get("amount"),
    }, None


def calc_info_discreteness(
    symbol: str,
    bar: dict,
    config: InfoDiscretenessConfig,
) -> tuple[dict | None, str | None]:
    """信息离散度调整动量因子 (Da, Gurun & Warachka 2014, RFS)。

    ID = sign(PRET) * (%neg - %pos)，PRET 为形成期累计收益，
    %pos/%neg 为形成期内正/负收益日占比。
      ID < 0: 信息连续小步释放 -> 投资者反应不足 -> 动量强
      ID > 0: 信息一次性跳跃   -> 动量弱/反转
    factor_value = momentum * (1 - ID)：
      连续信息(1-ID>1)放大动量，离散信息(1-ID<1)压缩动量。
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    n = config.momentum_window
    win = prices[-n - 1:]
    momentum = win[-1] / win[0] - 1.0
    if not math.isfinite(momentum):
        return None, 'nan_momentum'

    daily_returns = [b / a - 1.0 for a, b in zip(win, win[1:]) if a > 0]
    if len(daily_returns) < 10:
        return None, 'insufficient_returns'

    pos_days = sum(1 for r in daily_returns if r > 0)
    neg_days = sum(1 for r in daily_returns if r < 0)
    n_days = len(daily_returns)
    pct_pos = pos_days / n_days
    pct_neg = neg_days / n_days

    sign_pret = 0.0 if abs(momentum) < 1e-12 else (1.0 if momentum > 0 else -1.0)
    id_value = sign_pret * (pct_neg - pct_pos)  # ∈ [-1, 1]

    factor_value = momentum * (1.0 - id_value)

    vol = _annualized_volatility(daily_returns) if len(daily_returns) >= 5 else 0.0

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "information_discreteness": id_value,
        "momentum": momentum,
        "pct_pos": pct_pos,
        "pct_neg": pct_neg,
        "volatility": vol,
        "amount": bar.get("amount"),
    }, None


def calc_hurst_trend(
    symbol: str,
    bar: dict,
    config: HurstConfig,
) -> tuple[dict | None, str | None]:
    """分形趋势因子 (R/S 分析)。

    H = log(R/S) 对 log(lag) 回归的斜率。
      H > 0.5: 趋势持续 -> 动量有效
      H < 0.5: 均值回归 -> 动量无效/反转
    factor_value = momentum * (H - 0.5) * 2
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    window = min(config.window, len(prices) - 1)
    win = prices[-window:]
    momentum = prices[-1] / prices[-config.momentum_window - 1] - 1.0

    hurst = _hurst_exponent(win)
    if hurst is None:
        return None, 'hurst_unstable'

    factor_value = momentum * (hurst - 0.5) * 2.0

    daily_returns = [b / a - 1.0 for a, b in zip(win, win[1:]) if a > 0]
    vol = _annualized_volatility(daily_returns) if len(daily_returns) >= 5 else 0.0

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "hurst": hurst,
        "momentum": momentum,
        "volatility": vol,
        "amount": bar.get("amount"),
    }, None


def calc_realized_kurt(
    symbol: str,
    bar: dict,
    config: RealizedKurtConfig,
) -> tuple[dict | None, str | None]:
    """已实现峰度/尾部风险惩罚因子 (Amaya et al. 2015, JFE)。

    RKURT = N * Σr^4 / (Σr^2)^2，窗口内日收益的峰度。
    高峰度 = 尾部事件多（暴涨暴跌）= 持有风险高，实证负向。
    factor_value = momentum / (1 + RKURT/5)：尾部风险高的动量被压缩。
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    kwin = min(config.kurt_window, len(prices) - 1)
    kprices = prices[-kwin - 1:]
    krets = [b / a - 1.0 for a, b in zip(kprices, kprices[1:]) if a > 0]
    if len(krets) < 10:
        return None, 'insufficient_kurt_returns'

    mom_prices = prices[-config.momentum_window - 1:]
    momentum = mom_prices[-1] / mom_prices[0] - 1.0

    sum_sq = sum(r * r for r in krets)
    sum_four = sum(r ** 4 for r in krets)
    if sum_sq <= 0 or not math.isfinite(sum_four):
        return None, 'zero_variance'
    rkurt = len(krets) * sum_four / (sum_sq * sum_sq)

    factor_value = momentum / (1.0 + rkurt / 5.0)

    vol = _annualized_volatility(krets)

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "realized_kurtosis": rkurt,
        "momentum": momentum,
        "volatility": vol,
        "amount": bar.get("amount"),
    }, None


def calc_52wh_idmom(
    symbol: str,
    bar: dict,
    config: Combined52WHIDConfig,
) -> tuple[dict | None, str | None]:
    """52WH × IDMOM 组合因子。

    factor_value = 52wh_ratio * (1 - ID)，52wh_ratio = close / 252日最高。
    ID = sign(PRET) * (%neg - %pos) ∈ [-1, 1]：
      连续信息 ID<0 -> 1-ID>1 -> 放大；离散信息 ID>0 -> 压缩。
    id_filter > 0 时，ID 超过过滤线的标的 factor_value 置 0（排除）。
    """
    prices = _to_prices(bar)
    if prices is None:
        return None, 'invalid_prices'
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'

    window = min(config.high_window, len(prices) - 1)
    high = max(prices[-window:])
    if high <= 0:
        return None, 'invalid_high'
    ratio = prices[-1] / high
    if not math.isfinite(ratio):
        return None, 'nan_ratio'

    # ID 计算（窗口内日收益的正负日占比）
    n = config.id_window
    win = prices[-n - 1:]
    momentum = win[-1] / win[0] - 1.0
    daily_returns = [b / a - 1.0 for a, b in zip(win, win[1:]) if a > 0]
    if len(daily_returns) < 10:
        return None, 'insufficient_returns'
    pos_days = sum(1 for r in daily_returns if r > 0)
    neg_days = sum(1 for r in daily_returns if r < 0)
    n_days = len(daily_returns)
    pct_pos = pos_days / n_days
    pct_neg = neg_days / n_days
    sign_pret = 0.0 if abs(momentum) < 1e-12 else (1.0 if momentum > 0 else -1.0)
    id_value = sign_pret * (pct_neg - pct_pos)

    quality = 1.0 - id_value
    if config.id_filter > 0 and id_value > config.id_filter:
        factor_value = 0.0          # 离散信息过滤
    else:
        factor_value = ratio * quality

    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "ratio": ratio,
        "information_discreteness": id_value,
        "quality": quality,
        "momentum": momentum,
        "high_window": window,
        "amount": bar.get("amount"),
    }, None


def _hurst_exponent(prices: list[float], max_lag: int = 40) -> float | None:
    """用 R/S 分析计算 Hurst 指数。

    将窗口切成若干子段，对每个子段计算 R/S，再对 log(lag) 与 log(mean R/S)
    做线性回归，斜率即 H。子段不足时返回 None。
    """
    n = len(prices)
    if n < 32:
        return None
    points = []
    for lag in range(2, max_lag + 1):
        rs_list = []
        start = 0
        while start + lag < n:
            segment = prices[start:start + lag + 1]
            seg_len = len(segment)
            mean = sum(segment) / seg_len
            devs = [p - mean for p in segment]
            cumsum = []
            c = 0.0
            for d in devs:
                c += d
                cumsum.append(c)
            r = max(cumsum) - min(cumsum)
            var = sum(d * d for d in devs) / seg_len
            s = math.sqrt(var)
            if s > 0 and r > 0:
                rs_list.append(r / s)
            start += lag
        if len(rs_list) >= 4:
            mean_rs = sum(rs_list) / len(rs_list)
            if mean_rs > 0:
                points.append((math.log(lag), math.log(mean_rs)))
    if len(points) < 4:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    m = len(xs)
    mx = sum(xs) / m
    my = sum(ys) / m
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 0:
        return None
    h = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return max(0.0, min(1.0, h))


# --- Helper ---

def _annualized_volatility(daily_returns: list[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(252)
