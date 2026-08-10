# -*- coding: utf-8 -*-
"""
聚宽回测: 缠论简化版 — 分型 + MACD背离 (510300)
=================================================
缠论全量化非常困难 (包含关系、递归线段、中枢、级别嵌套),
这里提取最核心且可量化的两个要素:

  底分型: 连续3根K线, 中间最低 (止跌结构)
  顶分型: 连续3根K线, 中间最高 (滞涨结构)

  MACD底背离: 价格新低 + MACD柱不新低 → 下跌动能衰竭 → 一买
  MACD顶背离: 价格新高 + MACD柱不新高 → 上涨动能衰竭 → 一卖

回测参数建议:
  起止日期: 自行选择
  初始资金: 100,000 | 频率: 日 | 基准: 沪深300
"""

import numpy as np
import talib

SYMBOL          = '510300.XSHG'
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9
LOOKBACK        = 60       # 背离检测回顾窗口
MIN_HISTORY     = 100
COMMISSION_RATE = 0.0003
SLIPPAGE_RATE   = 0.001


def initialize(context):
    set_benchmark('000300.XSHG')
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=COMMISSION_RATE, close_commission=COMMISSION_RATE,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(FixedSlippage(SLIPPAGE_RATE))

    g.symbol      = SYMBOL
    g.lookback    = LOOKBACK
    g.in_position = False
    g.entry_price = 0
    g.ready       = False
    g.day_counter = 0
    g.last_signal = ''

    run_daily(daily_check, time='9:31')
    log.info('缠论分型+MACD背离 策略初始化')


def daily_check(context):
    g.day_counter += 1
    if not g.ready:
        if g.day_counter < MIN_HISTORY:
            return
        g.ready = True

    df = attribute_history(
        g.symbol, count=g.lookback + 5,
        unit='1d', fields=['close', 'high', 'low'],
        skip_paused=True, df=True, fq='pre',
    )
    if df is None or len(df) < g.lookback:
        return

    closes = df['close'].values
    highs  = df['high'].values
    lows   = df['low'].values
    latest_close = closes[-1]

    # ---- MACD ----
    macd_line, macd_signal, hist = talib.MACD(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    if len(hist) < 5 or np.isnan(hist[-1]):
        return

    # ---- 分型识别 ----
    # 底分型: 最近3根, 中间最低
    is_bottom_fx = (lows[-3] > lows[-2] and lows[-1] > lows[-2] and
                    closes[-2] < closes[-3] and closes[-2] < closes[-1])

    # 顶分型: 最近3根, 中间最高
    is_top_fx = (highs[-3] < highs[-2] and highs[-1] < highs[-2] and
                 closes[-2] > closes[-3] and closes[-2] > closes[-1])

    # ---- 背离检测 ----
    # 默认无背离；条件块满足时才置真（必须先初始化，避免 UnboundLocalError）
    bearish_div = False
    bullish_div = False

    # 底背离: 价格新低 + MACD柱不新低
    recent_lows = lows[-g.lookback:]
    price_low_idx = np.argmin(recent_lows)
    hist_recent = hist[-len(recent_lows):] if len(hist) >= len(recent_lows) else hist
    if len(hist_recent) > price_low_idx:
        hist_at_price_low = hist_recent[price_low_idx]
        current_hist = hist[-1]
        price_at_low = recent_lows[price_low_idx]

        # 当前价格接近或低于前低, 但MACD柱比那时高 → 底背离
        bearish_div = (latest_close <= price_at_low * 1.01 and
                       current_hist > hist_at_price_low and
                       hist_at_price_low < 0)

    # 顶背离: 价格新高 + MACD柱不新高
    recent_highs = highs[-g.lookback:]
    price_high_idx = np.argmax(recent_highs)
    if len(hist_recent) > price_high_idx:
        hist_at_price_high = hist_recent[price_high_idx]
        current_hist = hist[-1]

        bullish_div = (latest_close >= recent_highs[price_high_idx] * 0.99 and
                       current_hist < hist_at_price_high and
                       hist_at_price_high > 0)

    # ---- 买卖信号 ----
    signal = None

    # 买入: 底分型出现 + MACD底背离, 且不在持仓中
    if not g.in_position and is_bottom_fx and bearish_div:
        signal = 'buy'
        g.last_signal = '一买(底分型+底背离)'

    # 卖出: 顶分型出现 + MACD顶背离
    elif g.in_position and is_top_fx and bullish_div:
        signal = 'sell'
        g.last_signal = '一卖(顶分型+顶背离)'

    # 止损: 跌破前低
    elif g.in_position:
        recent_swing_low = min(lows[-20:])
        if latest_close < recent_swing_low:
            signal = 'sell'
            g.last_signal = '止损(破20日低点)'

    # ---- 执行 ----
    if signal == 'buy':
        target = context.portfolio.total_value
        log.info('%s close=%.3f macd_hist=%.4f' % (g.last_signal, latest_close, hist[-1]))
        order_target_value(g.symbol, target)
        g.in_position = True
        g.entry_price = latest_close

    elif signal == 'sell':
        ret = (latest_close - g.entry_price) / g.entry_price * 100 if g.entry_price > 0 else 0
        log.info('%s close=%.3f 收益率=%.2f%%' % (g.last_signal, latest_close, ret))
        order_target_value(g.symbol, 0)
        g.in_position = False
        g.entry_price = 0
