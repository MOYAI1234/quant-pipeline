# -*- coding: utf-8 -*-
"""
聚宽回测: 股债风险平价 (510300 + 511010)
==========================================
不做任何择时/预测。只做两件事:
  1. 永远同时持有 50%股票 + 50%债券
  2. 每个季度末再平衡回 50/50

为什么能赚钱:
  - 股票涨时, 自动卖股买债 (高位减仓)
  - 股票跌时, 自动卖债买股 (低位加仓)
  - 股债负相关性提供天然对冲, 暴跌时债券往往涨

回测参数建议:
  起止日期: 2015-01-01 ~ 2026-07-20
  初始资金: 100,000 | 频率: 日 | 基准: 沪深300
"""

STOCK_ETF    = '510300.XSHG'   # 沪深300ETF
BOND_ETF     = '511010.XSHG'   # 国债ETF (5年期)
STOCK_WEIGHT = 0.50            # 股票目标权重
BOND_WEIGHT  = 0.50            # 债券目标权重
COMMISSION   = 0.0003
SLIPPAGE     = 0.001

# 季度末月份
QUARTER_END_MONTHS = [3, 6, 9, 12]


def initialize(context):
    set_benchmark('000300.XSHG')
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=COMMISSION, close_commission=COMMISSION,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(FixedSlippage(SLIPPAGE))

    g.stock_etf   = STOCK_ETF
    g.bond_etf    = BOND_ETF
    g.stock_w     = STOCK_WEIGHT
    g.bond_w      = BOND_WEIGHT
    g.last_month  = None
    g.initialized = False

    run_daily(daily_check, time='9:31')
    log.info('股债50/50 季度再平衡 初始化')


def daily_check(context):
    dt = context.current_dt
    today = dt.date()

    # 第一天: 无论几月都先建仓
    if not g.initialized:
        g.initialized = True
        total = context.portfolio.total_value
        order_target_value(g.stock_etf, total * g.stock_w)
        order_target_value(g.bond_etf,  total * g.bond_w)
        log.info('初始建仓 %s 股票=%.0f 债券=%.0f' %
                 (today, total * g.stock_w, total * g.bond_w))
        g.last_month = today.month  # 起始月若为季度末, 跳过当月剩余交易日的再平衡
        return

    # 只在季度末月份触发一次
    if g.last_month is not None and today.month == g.last_month:
        return
    if today.month not in QUARTER_END_MONTHS:
        return
    g.last_month = today.month

    total = context.portfolio.total_value
    stock_target = total * g.stock_w
    bond_target  = total * g.bond_w

    log.info('=' * 40)
    log.info('季度再平衡 %s  总资产=%.0f' % (today, total))

    stock_before = context.portfolio.positions[g.stock_etf].value if g.stock_etf in context.portfolio.positions else 0
    bond_before  = context.portfolio.positions[g.bond_etf].value if g.bond_etf in context.portfolio.positions else 0
    log.info('调整前: 股票=%.0f(%.0f%%) 债券=%.0f(%.0f%%)' %
             (stock_before, stock_before/total*100 if total>0 else 0,
              bond_before, bond_before/total*100 if total>0 else 0))

    order_target_value(g.stock_etf, stock_target)
    order_target_value(g.bond_etf,  bond_target)

    log.info('调整后: 股票=%.0f(50%%) 债券=%.0f(50%%)' % (stock_target, bond_target))
