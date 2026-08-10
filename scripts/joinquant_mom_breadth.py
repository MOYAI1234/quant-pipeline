# -*- coding: utf-8 -*-
"""
聚宽回测: MOM-BREADTH 动量广度择时 (510300)
=============================================
不看RSI, 不看均线, 只统计阳线占比:

  近20日阳线 > 65% 且 近10日阳线 > 50%  →  做多 (强势)
  近10日阳线 < 30% 且 5日动量 < 0       →  平仓 (弱势)
  其他                                 →  不动

核心理念: 统计比预测可靠。连续收阳=趋势确认, 连续收阴=回避。

回测参数建议:
  起止日期: 自行选择
  初始资金: 100,000 | 频率: 日 | 基准: 沪深300
"""

SYMBOL             = '510300.XSHG'
PERIOD_STRONG      = 20        # 强势判断窗口
THRESHOLD_STRONG   = 0.65      # 近20日阳线占比 > 此值 → 做多
PERIOD_WEAK        = 10        # 弱势判断窗口
THRESHOLD_WEAK     = 0.30      # 近10日阳线占比 < 此值 → 平仓
MIN_HISTORY        = 40
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

    g.symbol       = SYMBOL
    g.period_strong = PERIOD_STRONG
    g.th_strong    = THRESHOLD_STRONG
    g.period_weak  = PERIOD_WEAK
    g.th_weak      = THRESHOLD_WEAK
    g.min_history  = MIN_HISTORY
    g.in_position  = False
    g.ready        = False
    g.day_counter  = 0

    run_daily(daily_check, time='9:31')
    log.info('MOM-BREADTH 动量广度策略 初始化')


def daily_check(context):
    g.day_counter += 1
    if not g.ready:
        if g.day_counter < g.min_history:
            return
        g.ready = True

    df = attribute_history(
        g.symbol, count=g.period_strong + 5,
        unit='1d', fields=['close'], skip_paused=True, df=True, fq='pre',
    )
    if df is None or len(df) < g.period_strong + 1:
        return

    closes = df['close'].values

    # 近20日阳线占比
    up_days_20 = sum(1 for i in range(-g.period_strong, 0) if closes[i] > closes[i-1])
    up_ratio_20 = up_days_20 / g.period_strong

    # 近10日阳线占比
    up_days_10 = sum(1 for i in range(-g.period_weak, 0) if closes[i] > closes[i-1])
    up_ratio_10 = up_days_10 / g.period_weak

    # 5日动量
    mom_5d = closes[-1] / closes[-6] - 1.0 if len(closes) >= 6 else 0

    signal = None

    if not g.in_position and up_ratio_20 > g.th_strong and up_ratio_10 > 0.5:
        signal = 'buy'
    elif g.in_position and up_ratio_10 < g.th_weak and mom_5d < 0:
        signal = 'sell'

    if signal == 'buy':
        target = context.portfolio.total_value
        log.info('入场 up20=%.0f%% up10=%.0f%% mom5=%.2f%% 仓位=%.0f' %
                 (up_ratio_20 * 100, up_ratio_10 * 100, mom_5d * 100, target))
        order_target_value(g.symbol, target)
        g.in_position = True

    elif signal == 'sell':
        log.info('离场 up10=%.0f%% mom5=%.2f%%' % (up_ratio_10 * 100, mom_5d * 100))
        order_target_value(g.symbol, 0)
        g.in_position = False
