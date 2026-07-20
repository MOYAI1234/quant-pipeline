# -*- coding: utf-8 -*-
"""
聚宽回测: SHARPE因子 ETF轮动策略
====================================
因子逻辑: 60日动量 / 60日年化波动率 = 夏普调整动量
        SHARPE = momentum_60d / (daily_ret_std * sqrt(252))

在每个调仓日，计算ETF池中所有标的的SHARPE值，选出最高的2只等权持有。
只买入SHARPE > 0 的正向标的，全部不达标时空仓。

回测参数建议:
  起止日期: 2025-07-09 ~ 2026-07-09
  初始资金: 100,000
  频率: 日
  基准: 沪深300
"""

import numpy as np
import pandas as pd

# ============================================================
# 策略参数 (可直接修改)
# ============================================================
ETF_POOL = [
    '510300.XSHG',  # 沪深300ETF (华泰柏瑞)
    '510500.XSHG',  # 中证500ETF (南方)
    '159915.XSHE',  # 创业板ETF (易方达)
    '512100.XSHG',  # 中证1000ETF (南方)
    '512880.XSHG',  # 证券ETF (国泰)
    '159920.XSHE',  # 恒生ETF (华夏)
    '513100.XSHG',  # 纳指ETF (国泰)
    '588000.XSHG',  # 科创50ETF (华夏)
    '516160.XSHG',  # 新能源ETF (南方)
    '159865.XSHE',  # 养殖ETF (国泰)
]

MOMENTUM_WINDOW    = 60    # 动量计算窗口 (交易日)
VOLATILITY_WINDOW  = 60    # 波动率计算窗口 (交易日)
MIN_HISTORY_DAYS   = 120   # 最少需要的历史数据天数
MAX_HOLDINGS       = 2     # 最大持仓数
REBALANCE_STEP     = 5     # 每 N 个交易日调仓一次
COMMISSION_RATE    = 0.0003  # 手续费 万三
SLIPPAGE_RATE      = 0.001   # 滑点 0.1%

# ============================================================
# 初始化
# ============================================================
def initialize(context):
    """策略初始化，只执行一次。"""
    # 基准: 沪深300
    set_benchmark('000300.XSHG')

    # 手续费 & 滑点 (ETF场内交易, 费率同股票)
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

    # 全局变量
    g.etf_pool           = ETF_POOL
    g.momentum_window    = MOMENTUM_WINDOW
    g.volatility_window  = VOLATILITY_WINDOW
    g.min_history_days   = MIN_HISTORY_DAYS
    g.max_holdings       = MAX_HOLDINGS
    g.rebalance_step     = REBALANCE_STEP
    g.day_counter        = 0
    g.ready              = False

    # 用 run_daily 替代 handle_data (聚宽推荐)
    run_daily(daily_check, time='9:31')

    log.info('=' * 50)
    log.info('SHARPE因子 ETF轮动策略 初始化完成')
    log.info(f'ETF池: {len(g.etf_pool)}只')
    log.info(f'动量窗口: {g.momentum_window}天')
    log.info(f'波动率窗口: {g.volatility_window}天')
    log.info(f'最大持仓: {g.max_holdings}只')
    log.info(f'调仓周期: 每{g.rebalance_step}天')
    log.info('=' * 50)


# ============================================================
# 每日主逻辑
# ============================================================
def daily_check(context):
    """每日运行，仅在调仓日执行实际交易。"""
    g.day_counter += 1

    # 检查数据是否就绪
    if not g.ready:
        days_needed = g.min_history_days + g.momentum_window
        if g.day_counter < days_needed:
            return
        g.ready = True
        log.info(f'历史数据就绪 (day {g.day_counter}), 开始调仓')

    # 只在调仓日执行
    if g.day_counter % g.rebalance_step != 0:
        return

    # ---------- 因子计算 & 排名 ----------
    scores = compute_sharpe_scores(context, g.etf_pool)

    if not scores:
        log.warn('无有效SHARPE评分, 跳过调仓')
        return

    # 选前N只 (且 SHARPE > 0)
    ranked = sorted(scores, key=lambda x: x['sharpe'], reverse=True)
    selected = []
    for item in ranked:
        if item['sharpe'] <= 0:
            continue
        if len(selected) >= g.max_holdings:
            break
        selected.append(item['symbol'])

    # ---------- 调仓 ----------
    rebalance(context, selected)

    # ---------- 日志 ----------
    log.info(
        f'[调仓] day={g.day_counter} '
        f'选中: {selected} '
        '排名: ' + str([(r['symbol'], round(r['sharpe'], 3)) for r in ranked[:5]])
    )


# ============================================================
# 因子计算: SHARPE = momentum_60d / annualized_vol_60d
# ============================================================
def compute_sharpe_scores(context, etf_list):
    """计算每只ETF的SHARPE因子值。

    Returns:
        list[dict]: [{'symbol': ..., 'sharpe': ..., 'momentum': ..., 'volatility': ...}, ...]
    """
    scores = []
    required_bars = g.momentum_window + 1  # 需要 N+1 根 bar 才能算 N 日收益率

    for symbol in etf_list:
        try:
            # 使用 attribute_history 获取历史数据
            # 参数: (security, count, unit, fields, skip_paused, df, fq)
            df = attribute_history(
                symbol,
                count=required_bars,
                unit='1d',
                fields=['close'],
                skip_paused=True,
                df=True,
                fq='pre',
            )
        except Exception as e:
            log.debug(f'{symbol} 数据获取失败: {e}')
            continue

        if df is None or len(df) < required_bars:
            log.debug(f'{symbol} 数据不足: {len(df) if df is not None else 0}/{required_bars}')
            continue

        closes = df['close'].values
        if len(closes) < required_bars:
            continue

        # 60日动量
        momentum = closes[-1] / closes[0] - 1.0

        # 60日日收益率 → 年化波动率
        daily_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                daily_returns.append(closes[i] / closes[i - 1] - 1.0)

        if len(daily_returns) < 10:
            continue

        daily_returns = np.array(daily_returns[-g.volatility_window:])
        daily_std = np.std(daily_returns, ddof=1)
        annual_vol = daily_std * np.sqrt(252)

        if annual_vol <= 0 or not np.isfinite(annual_vol):
            continue

        # SHARPE因子
        sharpe = momentum / annual_vol

        if np.isfinite(sharpe):
            scores.append({
                'symbol': symbol,
                'sharpe': float(sharpe),
                'momentum': float(momentum),
                'volatility': float(annual_vol),
            })

    return scores


# ============================================================
# 调仓执行
# ============================================================
def rebalance(context, selected):
    """根据选中列表调仓: 卖出不在列表的, 等权买入选中的。"""
    current_positions = context.portfolio.positions
    held_symbols = [s for s, p in current_positions.items() if p.total_amount > 0]

    # ---- 卖出 ----
    for symbol in held_symbols:
        if symbol not in selected:
            log.info(f'  卖出 {symbol}')
            order_target_value(symbol, 0)

    # ---- 买入 ----
    if not selected:
        return

    total_value = context.portfolio.total_value
    target_value = total_value / len(selected)

    for symbol in selected:
        current_value = 0
        if symbol in current_positions:
            current_value = current_positions[symbol].value

        # 只加仓, 不减仓 (由卖出逻辑处理不在列表的)
        if current_value < target_value * 0.95:
            log.info(f'  买入 {symbol} 目标 {target_value:.0f}')
            order_target_value(symbol, target_value)
