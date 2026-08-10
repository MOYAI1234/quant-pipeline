# -*- coding: utf-8 -*-
"""
聚宽回测: RSI-MREV v2 — 双模式自适应择时 (510300)
=====================================================
v1 的问题: RSI<35 在牛市中太罕见, 导致踏空大段涨幅
v2 的改进: 根据市场状态自动切换模式

  牛市模式 (close > EMA60):
    确认: RSI > 50 → 顺势做多
    离场: RSI > 80 (过热带止盈) 或 close < EMA60 (趋势破坏)

  熊市/震荡模式 (close < EMA60):
    入场: RSI < 40 → 超卖抄底
    离场: RSI > 70 (反弹到位走人)

回测参数建议:
  起止日期: 2025-01-01 ~ 2026-07-20
  初始资金: 100,000 | 频率: 日 | 基准: 沪深300
"""

import numpy as np
import talib

# ============================================================
# 参数
# ============================================================
SYMBOL             = '510300.XSHG'
EMA_PERIOD         = 60       # 长期均线, 判断牛熊分界
RSI_PERIOD         = 14

# 牛市模式
RSI_BULL_ENTRY     = 50       # RSI > 此值 + EMA之上 → 做多
RSI_BULL_EXIT      = 80       # RSI > 此值 → 过热止盈

# 熊市模式
RSI_BEAR_ENTRY     = 40       # RSI < 此值 + EMA之下 → 超卖
RSI_BEAR_EXIT      = 70       # RSI > 此值 → 反弹到位

MIN_HISTORY        = 90       # 最少历史K线 (EMA60 + RSI14 需要)
COMMISSION_RATE    = 0.0003
SLIPPAGE_RATE      = 0.001


def initialize(context):
    set_benchmark('000300.XSHG')
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=COMMISSION_RATE, close_commission=COMMISSION_RATE,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(FixedSlippage(SLIPPAGE_RATE))

    g.symbol          = SYMBOL
    g.ema_period      = EMA_PERIOD
    g.rsi_bull_entry  = RSI_BULL_ENTRY
    g.rsi_bull_exit   = RSI_BULL_EXIT
    g.rsi_bear_entry  = RSI_BEAR_ENTRY
    g.rsi_bear_exit   = RSI_BEAR_EXIT
    g.min_history     = MIN_HISTORY
    g.mode            = 'FLAT'   # FLAT / BULL / BEAR
    g.ready           = False
    g.day_counter     = 0

    run_daily(daily_check, time='9:31')
    log.info('RSI-MREV v2 双模式策略 初始化')


def daily_check(context):
    g.day_counter += 1
    if not g.ready:
        if g.day_counter < g.min_history:
            return
        g.ready = True

    # ---- 拉数据 ----
    df = attribute_history(
        g.symbol, count=g.ema_period + 5,
        unit='1d', fields=['close'], skip_paused=True, df=True, fq='pre',
    )
    if df is None or len(df) < g.ema_period + 1:
        return

    closes = df['close'].values
    latest_close = closes[-1]

    # EMA60
    ema60 = talib.EMA(closes, timeperiod=g.ema_period)[-1]
    if np.isnan(ema60):
        return

    # RSI14
    rsi_series = talib.RSI(closes, timeperiod=RSI_PERIOD)
    latest_rsi = rsi_series[-1]
    if np.isnan(latest_rsi):
        return

    # ---- 判断市场状态 ----
    is_bull_market = latest_close > ema60
    in_position = context.portfolio.positions[g.symbol].total_amount > 0

    # ---- 信号 ----
    signal = None  # None=不动, 'buy', 'sell'

    if is_bull_market:
        # 牛市: 顺势做多
        if not in_position and latest_rsi > g.rsi_bull_entry:
            signal = 'buy'
            g.mode = 'BULL'
        elif in_position and latest_rsi > g.rsi_bull_exit:
            signal = 'sell'
            g.mode = 'FLAT'
    else:
        # 熊市/震荡: 均值回归
        if not in_position and latest_rsi < g.rsi_bear_entry:
            signal = 'buy'
            g.mode = 'BEAR'
        elif in_position:
            if g.mode == 'BULL':
                # 趋势破坏保护: 牛市建仓后市场转熊(close 跌破 EMA60) → 强制离场
                signal = 'sell'
                g.mode = 'FLAT'
            elif latest_rsi > g.rsi_bear_exit:
                # 熊市超卖反弹到位
                signal = 'sell'
                g.mode = 'FLAT'

    # ---- 执行 ----
    if signal == 'buy':
        target = context.portfolio.total_value
        log.info('入场 mode=%s close=%.3f ema60=%.3f rsi=%.1f 仓位=%.0f' %
                 (g.mode, latest_close, ema60, latest_rsi, target))
        order_target_value(g.symbol, target)

    elif signal == 'sell':
        log.info('离场 mode=%s close=%.3f ema60=%.3f rsi=%.1f' %
                 (g.mode, latest_close, ema60, latest_rsi))
        order_target_value(g.symbol, 0)
