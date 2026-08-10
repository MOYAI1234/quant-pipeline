"""510300 单ETF择时因子模块。

与ETF轮动不同，单ETF的核心问题是：今天应该持有(Long)还是空仓(Flat)？

因子设计遵循两个方向：
  A. 趋势跟踪: 识别趋势并顺势做多
  B. 均值回归: 识别极端点位反向操作

每个因子输出 (signal, metadata)：
  signal: 1=做多, 0=空仓
  metadata: 因子诊断信息
"""

from __future__ import annotations

import math


# ============================================================
# 工具函数
# ============================================================

def _ema(values: list[float], period: int) -> list[float]:
    """计算指数移动平均。"""
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _sma(values: list[float], period: int) -> list[float]:
    """简单移动平均。"""
    if len(values) < period:
        return []
    return [sum(values[i:i+period]) / period for i in range(len(values) - period + 1)]


def _true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _rolling_max(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    return [max(values[i:i+period]) for i in range(len(values) - period + 1)]


def _rolling_min(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    return [min(values[i:i+period]) for i in range(len(values) - period + 1)]


def _rolling_sum(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    return [sum(values[i:i+period]) for i in range(len(values) - period + 1)]


def _rolling_std(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    result = []
    for i in range(len(values) - period + 1):
        window = values[i:i+period]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / (period - 1)
        result.append(math.sqrt(variance))
    return result


def _calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    """计算RSI。"""
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    # 初始均值
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    rsi_values = []
    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - 100 / (1 + rs))
    
    # Wilder平滑
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - 100 / (1 + rs))
    
    return rsi_values


def _calc_choppiness(highs: list[float], lows: list[float], closes: list[float],
                     period: int = 14) -> list[float]:
    """计算Choppiness Index (0-100).
    
    公式: CI = 100 * log10(SUM(ATR1, n) / (HH(n) - LL(n))) / log10(n)
    
    CI < 38.2: 趋势市场
    CI > 61.8: 震荡/choppy市场
    """
    n = len(closes)
    if n < period + 1:
        return []
    
    # True Range
    tr = []
    for i in range(1, n):
        tr.append(_true_range(highs[i], lows[i], closes[i-1]))
    
    ci_values = []
    for i in range(period - 1, len(tr)):
        tr_sum = sum(tr[i-period+1:i+1])
        hh = max(highs[i-period+2:i+2])
        ll = min(lows[i-period+2:i+2])
        price_range = hh - ll
        if price_range <= 0:
            ci_values.append(50.0)
            continue
        ratio = tr_sum / price_range
        if ratio <= 0:
            ci_values.append(50.0)
            continue
        ci = 100 * math.log10(ratio) / math.log10(period)
        ci_values.append(max(0, min(100, ci)))
    
    return ci_values


def _calc_adx(highs: list[float], lows: list[float], closes: list[float],
              period: int = 14) -> dict:
    """计算ADX, +DI, -DI。
    
    Returns:
        dict with 'adx', 'plus_di', 'minus_di' as lists
    """
    n = len(closes)
    if n < period * 2:
        return {'adx': [], 'plus_di': [], 'minus_di': []}
    
    # True Range
    tr = []
    plus_dm = []
    minus_dm = []
    
    for i in range(1, n):
        tr.append(_true_range(highs[i], lows[i], closes[i-1]))
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0)
        if down > up and down > 0:
            minus_dm.append(down)
        else:
            minus_dm.append(0)
    
    # 平滑 (Wilder)
    def wilder_smooth(values, period):
        result = [sum(values[:period])]
        for i in range(period, len(values)):
            result.append(result[-1] - result[-1]/period + values[i])
        return result
    
    atr = wilder_smooth(tr, period)
    pdi_raw = wilder_smooth(plus_dm, period)
    mdi_raw = wilder_smooth(minus_dm, period)
    
    plus_di = []
    minus_di = []
    adx_list = []
    dx_list = []
    
    for i in range(len(atr)):
        if atr[i] <= 0:
            plus_di.append(0)
            minus_di.append(0)
            dx_list.append(0)
        else:
            pdi = pdi_raw[i] / atr[i] * 100
            mdi = mdi_raw[i] / atr[i] * 100
            plus_di.append(pdi)
            minus_di.append(mdi)
            if pdi + mdi > 0:
                dx_list.append(abs(pdi - mdi) / (pdi + mdi) * 100)
            else:
                dx_list.append(0)
    
    # ADX = smoothed DX
    if len(dx_list) >= period:
        first_adx = sum(dx_list[:period]) / period
        adx_list.append(first_adx)
        for i in range(period, len(dx_list)):
            adx_list.append((adx_list[-1] * (period - 1) + dx_list[i]) / period)
    
    return {
        'adx': adx_list,
        'plus_di': plus_di,
        'minus_di': minus_di,
    }


def _calc_atr(highs: list[float], lows: list[float], closes: list[float],
              period: int = 14) -> list[float]:
    """计算ATR。"""
    n = len(closes)
    if n < period + 1:
        return []
    
    tr_list = []
    for i in range(1, n):
        tr_list.append(_true_range(highs[i], lows[i], closes[i-1]))
    
    atr = [sum(tr_list[:period]) / period]
    for i in range(period, len(tr_list)):
        atr.append((atr[-1] * (period - 1) + tr_list[i]) / period)
    
    return atr


# ============================================================
# 择时因子计算
# ============================================================

def factor_chop_filter(bars: list[dict]) -> dict:
    """CHOP-FILTER: EMA20趋势 + Choppiness过滤
    
    信号: close > EMA20 AND choppiness < 38.2 → 做多
         否则 → 空仓
    
    理念: 只在趋势清晰(不震荡)时顺势做多。
    """
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    
    if len(closes) < 30:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    ema20 = _ema(closes, 20)
    chop = _calc_choppiness(highs, lows, closes, 14)
    
    if not ema20 or not chop:
        return {'signal': 0, 'reason': 'insufficient_indicators'}
    
    # 对齐: ema20 和 chop 长度不同, 取最后共同的
    latest_close = closes[-1]
    latest_ema = ema20[-1]
    latest_chop = chop[-1] if chop else 50
    
    is_trending_up = latest_close > latest_ema
    is_not_choppy = latest_chop < 38.2
    
    if is_trending_up and is_not_choppy:
        return {
            'signal': 1,
            'reason': 'trend_up+not_choppy',
            'close': latest_close,
            'ema20': latest_ema,
            'choppiness': latest_chop,
        }
    else:
        reason_parts = []
        if not is_trending_up:
            reason_parts.append('below_ema')
        if not is_not_choppy:
            reason_parts.append(f'choppy({latest_chop:.1f})')
        return {
            'signal': 0,
            'reason': '+'.join(reason_parts),
            'close': latest_close,
            'ema20': latest_ema,
            'choppiness': latest_chop,
        }


def factor_adx_trend(bars: list[dict]) -> dict:
    """ADX-TREND: ADX趋势强度 + 方向确认
    
    信号: ADX(14) > 25 AND +DI > -DI → 做多
         否则 → 空仓
    
    理念: ADX是最经典的趋势强度指标，>25确认趋势存在，+DI>-DI确认方向。
    """
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    
    if len(closes) < 50:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    adx_data = _calc_adx(highs, lows, closes, 14)
    
    if not adx_data['adx']:
        return {'signal': 0, 'reason': 'insufficient_adx'}
    
    latest_adx = adx_data['adx'][-1]
    latest_pdi = adx_data['plus_di'][-1]
    latest_mdi = adx_data['minus_di'][-1]
    
    if latest_adx > 25 and latest_pdi > latest_mdi:
        return {
            'signal': 1,
            'reason': 'strong_trend',
            'close': closes[-1],
            'adx': latest_adx,
            'plus_di': latest_pdi,
            'minus_di': latest_mdi,
        }
    else:
        return {
            'signal': 0,
            'reason': 'no_trend_or_bearish' if latest_adx <= 25 else 'bearish',
            'close': closes[-1],
            'adx': latest_adx,
            'plus_di': latest_pdi,
            'minus_di': latest_mdi,
        }


def factor_rsi_mean_reversion(bars: list[dict]) -> dict:
    """RSI-MREV: RSI极值均值回归
    
    信号: RSI(14) < 35 → 做多(超卖反弹)
          RSI(14) > 75 → 空仓(超买)
          中间区域 → 保持上个信号(不轻易变)
    
    理念: 短期超卖往往是好的入场点，短期超买应该离场。
    注意：单方向策略只有做多和平仓，不做空。
    """
    closes = [b['close'] for b in bars]
    
    if len(closes) < 30:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    rsi_list = _calc_rsi(closes, 14)
    
    if not rsi_list:
        return {'signal': 0, 'reason': 'insufficient_rsi'}
    
    latest_rsi = rsi_list[-1]
    
    # 也参考短期动量：如果是超卖但还在加速下跌则等等
    mom_5d = closes[-1] / closes[-6] - 1.0 if len(closes) >= 6 else 0
    
    if latest_rsi < 35:
        # 超卖区域: 做多
        # 如果还在加速下跌，等一等 (RSI < 30 且 5日跌>3%)
        if latest_rsi < 30 and mom_5d < -0.03:
            return {
                'signal': 0,
                'reason': 'oversold_but_accelerating',
                'close': closes[-1],
                'rsi': latest_rsi,
                'mom_5d': mom_5d,
            }
        return {
            'signal': 1,
            'reason': 'oversold_bounce',
            'close': closes[-1],
            'rsi': latest_rsi,
            'mom_5d': mom_5d,
        }
    elif latest_rsi > 75:
        return {
            'signal': 0,
            'reason': 'overbought',
            'close': closes[-1],
            'rsi': latest_rsi,
            'mom_5d': mom_5d,
        }
    else:
        # 中间区域: 不产生新信号 (由backtest的持仓管理决定)
        return {
            'signal': -1,  # -1 = 保持现状
            'reason': 'neutral_zone',
            'close': closes[-1],
            'rsi': latest_rsi,
            'mom_5d': mom_5d,
        }


def factor_vol_breakout(bars: list[dict]) -> dict:
    """VOL-BREAK: 波动率扩张突破
    
    信号: ATR(14) / ATR平滑(20) > 1.3 AND close > EMA20 → 做多
          ATR回落 + close < EMA20 → 空仓
    
    理念: 波动率的急剧扩张往往伴随趋势启动。放量突破是可靠的入场信号。
    """
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    
    if len(closes) < 50:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    atr_list = _calc_atr(highs, lows, closes, 14)
    ema20 = _ema(closes, 20)
    
    if not atr_list or not ema20:
        return {'signal': 0, 'reason': 'insufficient_indicators'}
    
    latest_atr = atr_list[-1]
    latest_close = closes[-1]
    latest_ema = ema20[-1]
    
    # ATR 20日均值
    atr_ma20 = sum(atr_list[-20:]) / 20 if len(atr_list) >= 20 else latest_atr
    
    vol_expanding = latest_atr > atr_ma20 * 1.3
    trending_up = latest_close > latest_ema
    
    if vol_expanding and trending_up:
        return {
            'signal': 1,
            'reason': 'vol_breakout_up',
            'close': latest_close,
            'atr': latest_atr,
            'atr_ma': atr_ma20,
            'ema20': latest_ema,
            'vol_ratio': latest_atr / atr_ma20 if atr_ma20 > 0 else 0,
        }
    elif not trending_up:
        return {
            'signal': 0,
            'reason': 'below_ema',
            'close': latest_close,
            'atr': latest_atr,
            'atr_ma': atr_ma20,
            'ema20': latest_ema,
            'vol_ratio': latest_atr / atr_ma20 if atr_ma20 > 0 else 0,
        }
    else:
        # 此处仅剩: trending_up 为真 且 vol_expanding 为假
        return {
            'signal': 0,
            'reason': 'trending_but_no_vol',
            'close': latest_close,
            'atr': latest_atr,
            'atr_ma': atr_ma20,
            'ema20': latest_ema,
            'vol_ratio': latest_atr / atr_ma20 if atr_ma20 > 0 else 0,
        }


def factor_volume_climax(bars: list[dict]) -> dict:
    """VOL-CLIMAX: 放量恐慌底 + 逆势做多
    
    信号: 成交量 > 2x 20日均量 AND 价格接近20日最低价 → 做多(恐慌底)
          成交量正常 → 保持空仓
    
    理念: 放量暴跌是恐慌性抛售的特征，往往是短期底部。
          注意：必须有确认信号(次日不再新低)才能入场。
    """
    closes = [b['close'] for b in bars]
    volumes = [b.get('volume', 0) for b in bars]
    lows = [b['low'] for b in bars]
    
    if len(closes) < 30:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    latest_close = closes[-1]
    latest_volume = volumes[-1] if volumes[-1] > 0 else 0
    latest_low = lows[-1]
    
    # 20日均量
    vol_20 = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
    avg_vol_20 = sum(vol_20) / len(vol_20) if vol_20 else 1
    
    # 20日最低价
    low_20d = min(lows[-20:]) if len(lows) >= 20 else latest_low
    
    # 恐慌底条件: 放量 + 接近20日低点 + 收阳
    volume_spike = latest_volume > avg_vol_20 * 2.0 if avg_vol_20 > 0 else False
    near_low = (latest_low - low_20d) / low_20d < 0.02 if low_20d > 0 else False
    
    # 还需要收盘价回升确认 (蜡烛收阳)
    open_price = bars[-1].get('open', latest_close)
    candle_body_pct = (latest_close - open_price) / open_price if open_price > 0 else 0
    
    if volume_spike and near_low and candle_body_pct > 0.005:
        return {
            'signal': 1,
            'reason': 'panic_bottom',
            'close': latest_close,
            'volume': latest_volume,
            'avg_vol_20': avg_vol_20,
            'vol_ratio': latest_volume / avg_vol_20 if avg_vol_20 > 0 else 0,
            'candle_body': candle_body_pct,
        }
    
    # 离场信号: 成交量回落正常
    # len(closes) >= 30 已在上方保证, closes[-6] 安全访问
    if latest_volume < avg_vol_20 * 0.7 and latest_close < closes[-6]:
        return {
            'signal': 0,
            'reason': 'volume_normalizing',
            'close': latest_close,
            'volume': latest_volume,
            'avg_vol_20': avg_vol_20,
            'vol_ratio': latest_volume / avg_vol_20 if avg_vol_20 > 0 else 0,
        }
    
    return {
        'signal': -1,  # 保持
        'reason': 'no_signal' if not volume_spike else 'spike_not_confirmed',
        'close': latest_close,
        'volume': latest_volume,
        'avg_vol_20': avg_vol_20,
        'vol_ratio': latest_volume / avg_vol_20 if avg_vol_20 > 0 else 0,
    }


# ============================================================
# 第二组: 全新因子 (与RSI/动量正交)
# ============================================================

def factor_vol_panic(bars: list[dict]) -> dict:
    """VOL-PANIC: 波动率恐慌/贪婪区间
    
    不看价格方向, 只看波动率区间:
      ATR(20) / ATR(200) > 1.5 → 恐慌 → 做多(别人恐惧我贪婪)
      ATR(20) / ATR(200) < 0.7 → 安逸 → 平仓(太舒服该走了)
    
    理念: 极度恐慌是最佳买点, 极度安逸是最佳卖点。
    与RSI完全不同——RSI看超买超卖, 这个看情绪极值。
    """
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    
    if len(closes) < 220:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    atr20 = _calc_atr(highs, lows, closes, 20)
    atr200 = _calc_atr(highs, lows, closes, 200)
    
    if not atr20 or not atr200:
        return {'signal': 0, 'reason': 'insufficient_atr'}
    
    # 对齐: 取ATR200有值之后的最近ATR20
    latest_atr20 = atr20[-1]
    latest_atr200 = atr200[-1]
    
    if latest_atr200 <= 0:
        return {'signal': 0, 'reason': 'zero_atr200'}
    
    vol_ratio = latest_atr20 / latest_atr200
    
    if vol_ratio > 1.5:
        return {
            'signal': 1,
            'reason': 'panic',
            'close': closes[-1],
            'atr20': latest_atr20,
            'atr200': latest_atr200,
            'vol_ratio': vol_ratio,
        }
    elif vol_ratio < 0.7:
        return {
            'signal': 0,
            'reason': 'complacent',
            'close': closes[-1],
            'atr20': latest_atr20,
            'atr200': latest_atr200,
            'vol_ratio': vol_ratio,
        }
    else:
        return {
            'signal': -1,  # 中间区域保持
            'reason': 'normal',
            'close': closes[-1],
            'atr20': latest_atr20,
            'atr200': latest_atr200,
            'vol_ratio': vol_ratio,
        }


def factor_gap_reversal(bars: list[dict]) -> dict:
    """GAP-REV: 跳空缺口反转
    
    不看趋势, 不看RSI, 只抓跳空后的反向确认:
      昨日: 跳空低开>1% 且 收阳 → 今天开盘买, 持5天
      今日: 跳空高开>1% 且 收阴 → 平仓
    
    理念: 恐慌性跳空后的买方反击是最强的短线信号。
    纯事件驱动, 与所有趋势/均值因子正交。
    """
    if len(bars) < 3:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    today = bars[-1]
    yesterday = bars[-2]
    
    today_open = today.get('open', 0)
    today_close = today.get('close', 0)
    
    yesterday_open = yesterday.get('open', 0)
    yesterday_close = yesterday.get('close', 0)
    
    if yesterday_close <= 0 or yesterday_open <= 0:
        return {'signal': -1, 'reason': 'no_data'}
    
    # 今日跳空
    if today_open > 0 and yesterday_close > 0:
        # 昨天: 跳空低开 >1% 且 收阳 (买方反击)
        # 跳空低开: 开盘即大跌, 但收盘涨回来
        prev_prev_close = bars[-3].get('close', yesterday_close) if len(bars) >= 3 else yesterday_close
        overnight_gap = (yesterday_open - prev_prev_close) / prev_prev_close if prev_prev_close > 0 else 0
        
        # 恐慌跳空低开 + 收阳 = 买入信号
        is_panic_gap = overnight_gap < -0.015  # 跳空低开>1.5%
        is_bullish_reversal = yesterday_close > yesterday_open  # 收阳
        
        if is_panic_gap and is_bullish_reversal:
            return {
                'signal': 1,
                'reason': 'panic_gap_reversal',
                'close': today_close,
                'yesterday_gap': overnight_gap,
                'yesterday_body': yesterday_close - yesterday_open,
            }
        
        # 今日: 跳空高开 + 收阴 = 卖出信号
        today_overnight = (today_open - yesterday_close) / yesterday_close
        is_greedy_gap = today_overnight > 0.015
        is_bearish_candle = today_close < today_open and today_close < yesterday_close
        
        if is_greedy_gap and is_bearish_candle:
            return {
                'signal': 0,
                'reason': 'greedy_gap_reversal',
                'close': today_close,
                'today_gap': today_overnight,
            }
    
    return {'signal': -1, 'reason': 'no_gap_signal', 'close': today_close}


def factor_rsi_divergence(bars: list[dict]) -> dict:
    """RSI-DIV: RSI背离检测
    
    不看RSI绝对值, 看RSI与价格的背离:
      价格创新低 + RSI不创新低 → 看涨背离 → 做多
      价格创新高 + RSI不创新高 → 看跌背离 → 平仓
    
    理念: 背离是经典的反转信号, 比单一RSI阈值更可靠。
    """
    closes = [b['close'] for b in bars]
    
    if len(closes) < 30:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    rsi_list = _calc_rsi(closes, 14)
    if len(rsi_list) < 20:
        return {'signal': 0, 'reason': 'insufficient_rsi'}
    
    # 最近20日价格低点
    recent_closes = closes[-20:]
    recent_rsi = rsi_list[-20:]
    
    # 找最近的低点: 价格的最低5日
    price_low_idx = recent_closes.index(min(recent_closes)) if min(recent_closes) > 0 else -1
    
    # 看涨背离: 价格低点在过去10天, 但RSI现在比那时高
    if price_low_idx >= 10 and len(recent_rsi) > price_low_idx:
        price_low = recent_closes[price_low_idx]
        rsi_at_low = recent_rsi[price_low_idx]
        current_rsi = recent_rsi[-1]
        
        # 价格距低点回升 >1%, RSI回升 >5
        if closes[-1] > price_low * 1.01 and current_rsi > rsi_at_low + 5:
            return {
                'signal': 1,
                'reason': 'bullish_divergence',
                'close': closes[-1],
                'rsi': current_rsi,
                'rsi_at_low': rsi_at_low,
            }
    
    # 看跌背离: 价格创新高但RSI不配合
    price_high_idx = recent_closes.index(max(recent_closes[-10:]))
    if len(recent_rsi) > price_high_idx + 10:
        rsi_at_high = recent_rsi[price_high_idx + 10]
        current_rsi = recent_rsi[-1]
        
        if closes[-1] > max(recent_closes[-10:]) * 0.99 and current_rsi < rsi_at_high - 5:
            return {
                'signal': 0,
                'reason': 'bearish_divergence',
                'close': closes[-1],
                'rsi': current_rsi,
                'rsi_at_high': rsi_at_high,
            }
    
    return {'signal': -1, 'reason': 'no_divergence', 'close': closes[-1]}


def factor_mom_breadth(bars: list[dict]) -> dict:
    """MOM-BREADTH: 动量广度因子
    
    统计最近N天中有多少天收阳:
      近20日收阳 > 14天(70%) → 强势, 做多
      近10日收阳 < 3天(30%) → 弱势, 平仓
    
    理念: 不要预测, 只跟随——阳线占比是最简单的趋势判断。
    当市场连续收阳时顺势, 连续收阴时空仓。
    """
    closes = [b['close'] for b in bars]
    
    if len(closes) < 25:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    # 近20日阳线占比
    up_days_20 = sum(1 for i in range(-20, 0) if closes[i] > closes[i-1])
    up_ratio_20 = up_days_20 / 20
    
    # 近10日阳线占比
    up_days_10 = sum(1 for i in range(-10, 0) if closes[i] > closes[i-1])
    up_ratio_10 = up_days_10 / 10
    
    # 5日动量
    mom_5d = closes[-1] / closes[-6] - 1.0 if len(closes) >= 6 else 0
    
    if up_ratio_20 > 0.65 and up_ratio_10 > 0.5:
        return {
            'signal': 1,
            'reason': 'strong_breadth',
            'close': closes[-1],
            'up_ratio_20': up_ratio_20,
            'up_ratio_10': up_ratio_10,
            'mom_5d': mom_5d,
        }
    elif up_ratio_10 < 0.3 and mom_5d < 0:
        return {
            'signal': 0,
            'reason': 'weak_breadth',
            'close': closes[-1],
            'up_ratio_20': up_ratio_20,
            'up_ratio_10': up_ratio_10,
            'mom_5d': mom_5d,
        }
    else:
        return {
            'signal': -1,
            'reason': 'mixed',
            'close': closes[-1],
            'up_ratio_20': up_ratio_20,
            'up_ratio_10': up_ratio_10,
            'mom_5d': mom_5d,
        }


def factor_donchian_breakout(bars: list[dict]) -> dict:
    """DONCHIAN: Donchian通道突破
    
    纯价格突破, 不依赖RSI/量/波动率:
      close > 20日最高价 → 做多(突破新高)
      close < 10日最低价 → 平仓(趋势破坏)
      中间 → 保持
    
    理念: 价格突破是最原始的动量信号, 简单但可靠。
    """
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    
    if len(closes) < 25:
        return {'signal': 0, 'reason': 'insufficient_data'}
    
    latest_close = closes[-1]
    hh_20 = max(highs[-21:-1])  # 前20日最高价(不含今天)
    ll_10 = min(lows[-11:-1])   # 前10日最低价
    
    if latest_close > hh_20:
        return {
            'signal': 1,
            'reason': 'breakout_new_high',
            'close': latest_close,
            'hh_20': hh_20,
            'll_10': ll_10,
        }
    elif latest_close < ll_10:
        return {
            'signal': 0,
            'reason': 'breakdown',
            'close': latest_close,
            'hh_20': hh_20,
            'll_10': ll_10,
        }
    else:
        return {
            'signal': -1,
            'reason': 'inside_range',
            'close': latest_close,
            'hh_20': hh_20,
            'll_10': ll_10,
        }


FACTOR_REGISTRY = {
    'CHOP-FILTER': {
        'name': 'CHOP-FILTER',
        'description': 'EMA20趋势 + Choppiness过滤: 只在非震荡趋势中做多',
        'fn': factor_chop_filter,
        'category': 'trend',
    },
    'ADX-TREND': {
        'name': 'ADX-TREND',
        'description': 'ADX趋势强度+方向: ADX>25且+DI>-DI时做多',
        'fn': factor_adx_trend,
        'category': 'trend',
    },
    'RSI-MREV': {
        'name': 'RSI-MREV',
        'description': 'RSI极值均值回归: RSI<35超卖做多, RSI>75超买离场',
        'fn': factor_rsi_mean_reversion,
        'category': 'mean_reversion',
    },
    'VOL-BREAK': {
        'name': 'VOL-BREAK',
        'description': '波动率扩张突破: ATR飙升+EMA之上做多',
        'fn': factor_vol_breakout,
        'category': 'volatility',
    },
    'VOL-CLIMAX': {
        'name': 'VOL-CLIMAX',
        'description': '放量恐慌底: 天量+新低+收阳→逆势做多',
        'fn': factor_volume_climax,
        'category': 'volume',
    },
    'VOL-PANIC': {
        'name': 'VOL-PANIC',
        'description': '波动率恐慌区间: ATR飙升=恐慌做多, ATR萎缩=安逸平仓',
        'fn': factor_vol_panic,
        'category': 'volatility',
    },
    'GAP-REV': {
        'name': 'GAP-REV',
        'description': '跳空反转: 恐慌跳空低开+收阳=买, 贪婪跳空高开+收阴=卖',
        'fn': factor_gap_reversal,
        'category': 'event',
    },
    'DONCHIAN': {
        'name': 'DONCHIAN',
        'description': 'Donchian突破: 破20日高做多, 破10日低平仓',
        'fn': factor_donchian_breakout,
        'category': 'trend',
    },
    'RSI-DIV': {
        'name': 'RSI-DIV',
        'description': 'RSI背离: 价创新低RSI不跟=做多, 价创新高RSI不跟=平仓',
        'fn': factor_rsi_divergence,
        'category': 'divergence',
    },
    'MOM-BREADTH': {
        'name': 'MOM-BREADTH',
        'description': '动量广度: 近20日阳线>65%=强势做多, 近10日<30%=弱势平仓',
        'fn': factor_mom_breadth,
        'category': 'breadth',
    },
}
