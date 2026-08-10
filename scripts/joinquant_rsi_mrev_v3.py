# -*- coding: utf-8 -*-
"""
聚宽回测: RSI-MREV v3 — MA200趋势过滤 + RSI择时 (510300)
===========================================================
v2 的问题: EMA60 在慢熊市中滞后严重, 策略扛了整轮2022-2024熊市
v3 的改进: 用 MA200 做硬过滤, 铁律「熊市不玩」

逻辑:
  close < MA200  →  空仓 (无论RSI多少, 熊市不参与)
  close > MA200 且 RSI < 40   →  做多 (牛市超卖 = 黄金坑)
  close > MA200 且 RSI > 75   →  平仓 (过热止盈)
  其他情况 → 保持当前仓位

回测参数建议:
  起止日期: 2021-01-01 ~ 2026-07-20
  初始资金: 100,000 | 频率: 日 | 基准: 沪深300
"""

import numpy as np
import talib

SYMBOL             = '510300.XSHG'
MA_PERIOD          = 200      # 长期趋势过滤
RSI_PERIOD         = 14
RSI_OVERSOLD       = 40       # 牛市超卖入场
RSI_OVERBOUGHT     = 75       # 过热止盈
MIN_HISTORY        = 220
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

    g.symbol         = SYMBOL
    g.ma_period      = MA_PERIOD
    g.rsi_oversold   = RSI_OVERSOLD
    g.rsi_overbought = RSI_OVERBOUGHT
    g.min_history    = MIN_HISTORY
    g.ready          = False
    g.day_counter    = 0

    run_daily(daily_check, time='9:31')
    log.info('RSI-MREV v3 MA200过滤策略 初始化')


def daily_check(context):
    g.day_counter += 1
    if not g.ready:
        if g.day_counter < g.min_history:
            return
        g.ready = True

    df = attribute_history(
        g.symbol, count=MA_PERIOD + 5,
        unit='1d', fields=['close'], skip_paused=True, df=True, fq='pre',
    )
    if df is None or len(df) < MA_PERIOD + 1:
        return

    closes = df['close'].values
    latest_close = closes[-1]

    ma200 = talib.SMA(closes, timeperiod=MA_PERIOD)[-1]
    if np.isnan(ma200):
        return

    rsi_series = talib.RSI(closes, timeperiod=RSI_PERIOD)
    latest_rsi = rsi_series[-1]
    if np.isnan(latest_rsi):
        return

    # ---- 铁律 ----
    in_position = context.portfolio.positions[g.symbol].total_amount > 0
    if latest_close < ma200:
        # 熊市: 强制空仓
        if in_position:
            log.info('离场 MA200破位 close=%.3f ma200=%.3f rsi=%.1f' %
                     (latest_close, ma200, latest_rsi))
            order_target_value(g.symbol, 0)
        return

    # ---- 牛市区域 ----
    signal = None

    if not in_position and latest_rsi < g.rsi_oversold:
        signal = 'buy'
    elif in_position and latest_rsi > g.rsi_overbought:
        signal = 'sell'

    if signal == 'buy':
        target = context.portfolio.total_value
        log.info('入场 close=%.3f ma200=%.3f rsi=%.1f 仓位=%.0f' %
                 (latest_close, ma200, latest_rsi, target))
        order_target_value(g.symbol, target)

    elif signal == 'sell':
        log.info('离场 RSI过热 close=%.3f ma200=%.3f rsi=%.1f' %
                 (latest_close, ma200, latest_rsi))
        order_target_value(g.symbol, 0)
