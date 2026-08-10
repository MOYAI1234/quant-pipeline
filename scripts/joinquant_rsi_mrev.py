# -*- coding: utf-8 -*-
"""
聚宽回测: RSI-MREV 均值回归择时策略 (510300)
=================================================
策略逻辑:
  RSI(14) < 35  → 超卖区域, 做多
  RSI(14) > 75  → 超买区域, 平仓
  35 ≤ RSI ≤ 75 → 保持当前仓位不变

额外保护:
  RSI < 30 且 5日跌超3% → 暂不入场 (恐慌还在加速)

原始回测表现 (2024-07 ~ 2026-07):
  年化 +10.21% | 最大回撤 -10.28% | 夏普 0.97 | 胜率 50% | 持仓 54%

回测参数建议:
  起止日期: 2024-07-01 ~ 2026-07-21
  初始资金: 100,000
  频率: 日
  基准: 沪深300
"""

import numpy as np
import talib

# ============================================================
# 策略参数
# ============================================================
SYMBOL            = '510300.XSHG'   # 沪深300ETF
RSI_PERIOD        = 14              # RSI 计算周期
RSI_OVERSOLD      = 35              # 超卖阈值 (低于此值做多)
RSI_OVERBOUGHT    = 75              # 超买阈值 (高于此值平仓)
RSI_PANIC         = 30              # 恐慌阈值 (RSI极低+加速下跌=暂不入场)
MOM_PANIC         = -0.03           # 5日动量恐慌阈值 (-3%)
MIN_HISTORY       = 60              # 最少需要的历史K线数
COMMISSION_RATE   = 0.0003          # 手续费 万三
SLIPPAGE_RATE     = 0.001           # 滑点 0.1%


# ============================================================
# 初始化
# ============================================================
def initialize(context):
    set_benchmark('000300.XSHG')

    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=COMMISSION_RATE,
            close_commission=COMMISSION_RATE,
            close_today_commission=0,
            min_commission=5,
        ),
        type='stock',
    )
    set_slippage(FixedSlippage(SLIPPAGE_RATE))

    g.symbol          = SYMBOL
    g.rsi_period      = RSI_PERIOD
    g.rsi_oversold    = RSI_OVERSOLD
    g.rsi_overbought  = RSI_OVERBOUGHT
    g.rsi_panic       = RSI_PANIC
    g.mom_panic       = MOM_PANIC
    g.min_history     = MIN_HISTORY
    g.in_position     = False
    g.ready           = False
    g.day_counter     = 0

    run_daily(daily_check, time='9:31')

    log.info('=' * 50)
    log.info('RSI-MREV 均值回归择时策略 初始化')
    log.info('标的: %s' % g.symbol)
    log.info('超卖入场: RSI < %d' % g.rsi_oversold)
    log.info('超买离场: RSI > %d' % g.rsi_overbought)
    log.info('恐慌保护: RSI < %d 且 5日跌超 %.1f%%' % (g.rsi_panic, abs(g.mom_panic) * 100))
    log.info('=' * 50)


# ============================================================
# 每日主逻辑
# ============================================================
def daily_check(context):
    g.day_counter += 1

    if not g.ready:
        if g.day_counter < g.min_history:
            return
        g.ready = True
        log.info('数据就绪, day=%d, 开始运行' % g.day_counter)

    # ---- 拉数据 ----
    df = attribute_history(
        g.symbol,
        count=g.rsi_period + 10,  # 多拉几根保证RSI计算精度
        unit='1d',
        fields=['close'],
        skip_paused=True,
        df=True,
        fq='pre',
    )

    if df is None or len(df) < g.rsi_period + 1:
        return

    closes = df['close'].values

    # ---- 计算 RSI ----
    rsi_series = talib.RSI(closes, timeperiod=g.rsi_period)
    latest_rsi = rsi_series[-1]
    if np.isnan(latest_rsi):
        return

    # ---- 5日动量 ----
    mom_5d = closes[-1] / closes[-6] - 1.0 if len(closes) >= 6 else 0

    # ---- 信号判断 ----
    signal = None  # None = 保持, 'buy' = 入场, 'sell' = 离场
    in_position = context.portfolio.positions[g.symbol].total_amount > 0

    if latest_rsi < g.rsi_oversold:
        # 恐慌保护: RSI极低 + 还在加速跌 → 等一等
        if latest_rsi < g.rsi_panic and mom_5d < g.mom_panic:
            log.info(
                'RSI=%.1f 恐慌加速中(5日动量%.2f%%), 暂不入场' %
                (latest_rsi, mom_5d * 100)
            )
        elif not in_position:
            signal = 'buy'
        # else: 已持仓, 超卖区域继续持

    elif latest_rsi > g.rsi_overbought:
        if in_position:
            signal = 'sell'

    # ---- 执行 ----
    if signal == 'buy':
        target_value = context.portfolio.total_value
        log.info('入场 RSI=%.1f 5日动量=%.2f%% 目标仓位=%.0f' %
                 (latest_rsi, mom_5d * 100, target_value))
        order_target_value(g.symbol, target_value)

    elif signal == 'sell':
        log.info('离场 RSI=%.1f' % latest_rsi)
        order_target_value(g.symbol, 0)
