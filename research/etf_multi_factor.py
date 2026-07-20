"""ETF 多因子研究模块。

在现有动量轮动基础上，新增以下因子用于对比回测：

  FACTOR-002: VW-MOM  (成交量加权动量)
  FACTOR-003: SHARPE   (夏普调整动量)
  FACTOR-004: MA-STATE (均线状态 + 自适应动量)

每个因子产出 ranking score，配合回测脚本对比表现。
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# --- Factor Configs ---

@dataclass(frozen=True)
class VWMomConfig:
    """成交量加权动量因子配置"""
    momentum_window: int = 60
    volume_window: int = 20       # 用于计算平均成交量的窗口
    min_history_days: int = 120
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.momentum_window + 1, self.min_history_days)


@dataclass(frozen=True)
class SharpeMomConfig:
    """夏普调整动量因子配置"""
    momentum_window: int = 60
    volatility_window: int = 20
    min_history_days: int = 120
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.momentum_window + 1, self.volatility_window + 1, self.min_history_days)


@dataclass(frozen=True)
class MAStateConfig:
    """均线状态因子配置"""
    short_ma: int = 20
    long_ma: int = 60
    momentum_window: int = 60
    min_history_days: int = 120
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.long_ma + 1, self.momentum_window + 1, self.min_history_days)


@dataclass(frozen=True)
class RetSkewConfig:
    """收益偏度因子配置"""
    skew_window: int = 60
    min_history_days: int = 120
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.skew_window + 1, self.min_history_days)


@dataclass(frozen=True)
class VolSurgeConfig:
    """成交量异动因子配置"""
    vol_lookback: int = 20
    surge_threshold: float = 1.5
    min_history_days: int = 120
    max_holdings: int = 2
    min_avg_amount: float | None = None

    @property
    def required_prices(self) -> int:
        return max(self.vol_lookback + 1, self.min_history_days)


# --- Factor Computation ---

def calc_vw_momentum(
    symbol: str,
    bar: dict,
    config: VWMomConfig,
) -> tuple[dict | None, str | None]:
    """成交量加权动量因子。

    结合价格动量和成交量变化:
      signal = momentum_20d * 0.5 + volume_growth * 0.5
      volume_growth = (today_amount / avg_amount_20d) - 1  (capped in [-0.5, 0.5])
      momentum_20d = close / close_20d_ago - 1

    与BASELINE(60d动量)形成差异化: 更短的窗口 + 成交量维度。
    理念: 短期趋势 + 放量确认 = 更强的信号。
    """
    prices = bar.get("prices", [])
    if isinstance(prices, str):
        prices = [float(p) for p in prices.split("|") if p]
    
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'
    
    prices = [float(p) for p in prices]
    if any(p <= 0 or not math.isfinite(p) for p in prices):
        return None, 'invalid_prices'
    
    amount = bar.get("amount", 0)
    
    # 20日短周期动量（与BASELINE的60日区别）
    mom_20d = prices[-1] / prices[-21] - 1.0 if len(prices) >= 21 else 0
    
    # 成交量增长信号（用成交额代理成交量）
    volume_growth = 0.0
    if amount and amount > 0:
        # amount是当日成交额，设为1.0表示"持平"，无法计算增长率时用中性值
        volume_growth = 0.0  # 中性
    
    # 如果动量很强，即使没有成交量数据也给予较好信号
    # 组合: 动量为主(0.7), 成交量调整为辅(0.3)
    vw_mom = mom_20d * 0.7 + volume_growth * 0.3
    
    # 波动率
    daily_returns = []
    for prev, curr in zip(prices[-22:], prices[-21:]):
        if prev > 0:
            daily_returns.append(curr / prev - 1.0)
    vol = _annualized_volatility(daily_returns) if len(daily_returns) >= 5 else 1.0
    
    return {
        "symbol": symbol,
        "factor_value": vw_mom,
        "momentum_20d": mom_20d,
        "volatility": vol,
        "amount": amount,
    }, None


def calc_sharpe_momentum(
    symbol: str,
    bar: dict,
    config: SharpeMomConfig,
) -> tuple[dict | None, str | None]:
    """夏普调整动量因子。

    60天收益率 / 60天年化波动率，衡量经风险调整后的趋势强度。
      信号 = momentum_60d / annualized_vol_60d

    理念: 同样的涨幅，低波动 > 高波动（趋势更稳健）。
    """
    prices = bar.get("prices", [])
    if isinstance(prices, str):
        prices = [float(p) for p in prices.split("|") if p]
    
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'
    
    prices = [float(p) for p in prices]
    if any(p <= 0 or not math.isfinite(p) for p in prices):
        return None, 'invalid_prices'
    
    amount = bar.get("amount")
    
    win = config.momentum_window + 1
    win_prices = prices[-win:]
    
    # 计算动量
    momentum = win_prices[-1] / win_prices[0] - 1.0
    if not math.isfinite(momentum):
        return None, 'nan_momentum'
    
    # 计算日收益率序列
    daily_returns = []
    for prev, curr in zip(win_prices, win_prices[1:]):
        if prev > 0:
            daily_returns.append(curr / prev - 1.0)
    
    if len(daily_returns) < 5:
        return None, 'insufficient_returns_for_vol'
    
    # 计算年化波动率
    ann_vol = _annualized_volatility(daily_returns[-config.volatility_window:])
    if ann_vol <= 0 or not math.isfinite(ann_vol):
        return None, 'nan_volatility'
    
    sharpe_mom = momentum / ann_vol if ann_vol > 0 else 0.0
    
    return {
        "symbol": symbol,
        "factor_value": sharpe_mom,
        "momentum": momentum,
        "volatility": ann_vol,
        "amount": amount,
    }, None


def calc_ma_state(
    symbol: str,
    bar: dict,
    config: MAStateConfig,
) -> tuple[dict | None, str | None]:
    """均线状态 + 自适应动量因子。

    先判断均线状态:
      - BULL:  短期MA > 长期MA（多头排列）
      - BEAR:  短期MA < 长期MA（空头排列）
    
    然后根据状态使用不同的子信号:
      - BULL: 动量因子（顺势做多）
      - BEAR: 反转因子（超跌反弹）
    
    理念: 不同市场环境下应使用不同的 alpha 来源。
    """
    prices = bar.get("prices", [])
    if isinstance(prices, str):
        prices = [float(p) for p in prices.split("|") if p]
    
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'
    
    prices = [float(p) for p in prices]
    if any(p <= 0 or not math.isfinite(p) for p in prices):
        return None, 'invalid_prices'
    
    amount = bar.get("amount")
    
    # 计算均线
    short_ma = sum(prices[-config.short_ma:]) / config.short_ma
    long_ma = sum(prices[-config.long_ma:]) / config.long_ma
    
    # 判断状态
    regime = "BULL" if short_ma > long_ma else "BEAR"
    
    if regime == "BULL":
        # 多头: 用动量
        momentum_base = prices[-config.momentum_window - 1]
        latest = prices[-1]
        signal = latest / momentum_base - 1.0
        
        # 动量 + 短期确认（加权）
        confirm_base = prices[-11]  # 10日确认
        confirm = latest / confirm_base - 1.0
        factor_value = 0.7 * signal + 0.3 * confirm
    else:
        # 空头: 用短期反转 + 超跌信号
        # 过去5日收益率（负得越多越好做反弹）
        ret_5d = prices[-1] / prices[-6] - 1.0 if len(prices) >= 6 else 0
        
        # 过去20日最低点到现在的距离
        recent_prices = prices[-20:]
        min_price = min(recent_prices)
        max_price = max(recent_prices)
        if max_price > min_price:
            reversal_potential = (prices[-1] - min_price) / (max_price - min_price)
        else:
            reversal_potential = 0.5
        
        # 综合: 短期超跌(负ret) + 已在反弹中(low reversal_potential near 1)
        # 空头市场中，刚反弹的信号更强
        if ret_5d < -0.03:
            factor_value = 0.5 * (1 - reversal_potential) + 0.5  # 超跌信号
        elif reversal_potential < 0.3:
            factor_value = 0.3 * (1 - reversal_potential)  # 底部区域
        else:
            factor_value = 0.0  # 不参与
    
    # 计算波动率用于后续排名
    daily_returns = []
    for prev, curr in zip(prices[-22:], prices[-21:]):
        if prev > 0:
            daily_returns.append(curr / prev - 1.0)
    volatility = _annualized_volatility(daily_returns) if daily_returns else 1.0
    
    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "regime": regime,
        "short_ma": short_ma,
        "long_ma": long_ma,
        "volatility": volatility,
        "amount": amount,
    }, None


def calc_ret_skew(
    symbol: str,
    bar: dict,
    config: RetSkewConfig,
) -> tuple[dict | None, str | None]:
    """收益偏度因子。

    测量日收益率分布的偏度（三阶矩）:
      skew = E[(r - mu)^3] / sigma^3

    正偏度 = 多大涨少大跌 → 看涨
    负偏度 = 多大跌少大涨 → 谨慎

    同时叠加动量方向: skew > 0 且 momentum > 0 → 最强信号
                       skew > 0 且 momentum < 0 → 蓄力信号

    理念: "右偏分布"意味着上行空间大于下行风险。
    """
    prices = bar.get("prices", [])
    if isinstance(prices, str):
        prices = [float(p) for p in prices.split("|") if p]
    
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'
    
    prices = [float(p) for p in prices]
    if any(p <= 0 or not math.isfinite(p) for p in prices):
        return None, 'invalid_prices'
    
    amount = bar.get("amount")
    
    # 计算日收益率序列
    win = config.skew_window + 1
    daily_returns = []
    for prev, curr in zip(prices[-win:], prices[-win+1:]):
        if prev > 0:
            daily_returns.append(curr / prev - 1.0)
    
    if len(daily_returns) < 10:
        return None, f'insufficient_returns len={len(daily_returns)}'
    
    # 均值和标准差
    mean_ret = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
    std_ret = math.sqrt(variance)
    
    if std_ret <= 0:
        return None, 'zero_variance'
    
    # 偏度
    skew = sum((r - mean_ret) ** 3 for r in daily_returns) / len(daily_returns) / (std_ret ** 3)
    
    # 动量方向
    momentum = prices[-1] / prices[-config.skew_window - 1] - 1.0
    
    # 合成信号:
    # 正偏度 + 正动量 = 强看涨 (1.0)
    # 正偏度 + 负动量 = 蓄力等待 (0.3)
    # 负偏度 = 回避 (0.0 or negative)
    if skew > 0.3 and momentum > 0:
        factor_value = skew * (1 + momentum)  # 放大好信号
    elif skew > 0.1:
        factor_value = skew * 0.5  # 偏度好但动量不行
    elif skew < -0.3:
        factor_value = skew  # 负偏度直接负分
    else:
        factor_value = skew * 0.3  # 中等
    
    # 波动率
    vol = _annualized_volatility(daily_returns)
    
    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "skewness": skew,
        "momentum": momentum,
        "volatility": vol,
        "amount": amount,
    }, None


def calc_vol_surge(
    symbol: str,
    bar: dict,
    config: VolSurgeConfig,
) -> tuple[dict | None, str | None]:
    """成交量异动因子。

    检测异常放量，结合价格方向:
      vol_ratio = today_volume / avg_volume_20d
      surge_signal = (vol_ratio - 1) * sign(momentum_20d)

    放量上涨 → 强烈看涨
    放量下跌 → 强烈看跌  
    缩量横盘 → 中性

    理念: 量在价先，异常量能预示趋势启动。
    """
    prices = bar.get("prices", [])
    if isinstance(prices, str):
        prices = [float(p) for p in prices.split("|") if p]
    
    if len(prices) < config.required_prices:
        return None, f'insufficient_prices len={len(prices)} need={config.required_prices}'
    
    prices = [float(p) for p in prices]
    if any(p <= 0 or not math.isfinite(p) for p in prices):
        return None, 'invalid_prices'
    
    amount = bar.get("amount", 0)
    volume = bar.get("volume", 0)
    
    # 20日动量
    mom_20d = prices[-1] / prices[-21] - 1.0 if len(prices) >= 21 else 0
    
    # 成交量比率（简化：使用amount/成交量作为代理）
    # 没有历史量数据，用价格波动作为量的代理
    # 逻辑：价格波动放大的ETF可能正处于资金关注期
    daily_returns = []
    for prev, curr in zip(prices[-22:], prices[-21:]):
        if prev > 0:
            daily_returns.append(curr / prev - 1.0)
    
    if len(daily_returns) < 5:
        return None, 'insufficient_returns'
    
    # 用近期波动率变化作为"量"的代理
    recent_vol_10d = _annualized_volatility(daily_returns[-10:]) if len(daily_returns) >= 10 else 1
    recent_vol_20d = _annualized_volatility(daily_returns) if len(daily_returns) >= 20 else 1
    
    if recent_vol_20d > 0:
        vol_surge = recent_vol_10d / recent_vol_20d - 1.0
    else:
        vol_surge = 0.0
    
    # 量价结合
    if vol_surge > 0.2 and mom_20d > 0:
        factor_value = vol_surge + mom_20d  # 放量上涨
    elif vol_surge > 0.2 and mom_20d < 0:
        factor_value = -abs(mom_20d) * 2  # 放量下跌 → 强回避
    elif vol_surge < -0.2:
        factor_value = mom_20d * 0.3  # 缩量 → 信号弱化
    else:
        factor_value = mom_20d * 0.5  # 正常
    
    return {
        "symbol": symbol,
        "factor_value": factor_value,
        "vol_surge": vol_surge,
        "momentum_20d": mom_20d,
        "volatility": recent_vol_20d,
        "amount": amount,
    }, None


# --- Combined Scoring & Ranking ---

@dataclass
class MultiFactorResult:
    """一次多因子评估的结果"""
    date: str
    selected: list[str]
    factor_name: str
    rankings: list[dict]
    rejections: list[dict]


def evaluate_multi_factor_snapshot(
    snapshot: dict,
    factor_config,
    factor_name: str,
    calc_fn,
) -> MultiFactorResult:
    """用指定因子评估一个快照，返回排序结果。"""
    date = snapshot.get("date", "")
    symbols = snapshot.get("symbols", {})
    
    factors = []
    rejections = []
    
    for symbol, bar in symbols.items():
        factor_result, reason = calc_fn(symbol, bar, factor_config)
        if factor_result is None:
            rejections.append({"symbol": symbol, "reason": reason})
        else:
            factors.append(factor_result)
    
    # 按 factor_value 降序排序
    ranked = sorted(factors, key=lambda f: f["factor_value"], reverse=True)
    
    max_holdings = getattr(factor_config, "max_holdings", 2)
    
    selected = []
    more_rejections = []
    
    for item in ranked:
        symbol = item["symbol"]
        if len(selected) >= max_holdings:
            more_rejections.append({
                "symbol": symbol,
                "reason": "capacity_limit",
                "factor": item,
            })
            continue
        
        # 正信号过滤: factor_value 必须 > 0
        if item.get("factor_value", 0) <= 0:
            more_rejections.append({
                "symbol": symbol,
                "reason": "non_positive_signal",
                "factor": item,
            })
            continue
        
        selected.append(symbol)
    
    return MultiFactorResult(
        date=date,
        selected=selected,
        factor_name=factor_name,
        rankings=[{
            "symbol": r["symbol"],
            "factor_value": r["factor_value"],
            "volatility": r.get("volatility", 0),
            "regime": r.get("regime", ""),
        } for r in ranked],
        rejections=rejections + more_rejections,
    )


def evaluate_history_with_factor(
    history: list[dict],
    factor_config,
    factor_name: str,
    calc_fn,
    *,
    rebalance_step: int = 5,
    limit: int | None = None,
) -> list[MultiFactorResult]:
    """用指定因子评估整个历史序列。"""
    results = []
    for index, snapshot in enumerate(history):
        if index % rebalance_step != 0:
            continue
        results.append(
            evaluate_multi_factor_snapshot(snapshot, factor_config, factor_name, calc_fn)
        )
        if limit is not None and len(results) >= limit:
            break
    return results


# --- Helper ---

def _annualized_volatility(daily_returns: list[float]) -> float:
    """从日收益率计算年化波动率。"""
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(252)


def _pct_returns(prices: list[float]) -> list[float]:
    returns = []
    for prev, curr in zip(prices, prices[1:]):
        if prev > 0:
            returns.append(curr / prev - 1.0)
    return returns
