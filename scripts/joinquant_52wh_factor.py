# -*- coding: utf-8 -*-
"""
聚宽回测: 52周高点距离(52WH)因子 ETF轮动策略
============================================
因子逻辑: 52WH = close / max(close[-252:])
        George & Hwang (2004) "The 52-Week High and Momentum Investing"
        Journal of Finance 59(5): 价格越接近过去252个交易日最高点,
        后续收益越强(锚定效应, 信息逐步兑现)。

在每个调仓日，计算ETF池中所有标的的52WH值，选出最高的2只等权持有。

与本地回测(quant-pipeline)对齐的参数:
  高点窗口: 252交易日  调仓周期: 每30个交易日  最大持仓: 2只
  warmup: 180交易日(数据就绪前不交易)
  费率: 佣金万三(最低5元) + 滑点0.1%  (与本地回测一致)

本地回测对照(2025-06-25 ~ 2026-06-25, 6只ETF池):
  52WH 年化 71.1% / 最大回撤 20.2% / 夏普 2.28 / 等权基准 21.4%

差异说明:
  - 聚宽用前复权价(fq='pre'), 本地tushare为不复权价; 52WH为相对比率,
    复权口径影响小, 但分红除息日在聚宽下不会出现虚假跳空, 更贴近真实持有收益
  - 调仓用当日开盘附近成交(聚宽按当前价), 本地用收盘价, 存在微小执行差异

回测参数建议:
  起止日期: 2025-06-25 ~ 2026-06-25 (或更长如 2024-01-02 起)
  初始资金: 100,000
  频率: 日
  基准: 沪深300 (000300.XSHG)
"""

import numpy as np

# ============================================================
# 策略参数 (可直接修改)
# ============================================================
ETF_POOL = [
    '159659.XSHE',  # 招商纳斯达克100ETF(QDII) (深市, 上市2023-04)
    '510300.XSHG',  # 华泰柏瑞沪深300ETF (沪市)
    '512400.XSHG',  # 南方中证申万有色金属ETF (沪市)
    '513010.XSHG',  # 易方达恒生科技ETF(QDII) (沪市)
    '515120.XSHG',  # 广发中证创新药产业ETF (沪市)  ← 注意是沪市, 不是XSHE!
    '518880.XSHG',  # 华安易富黄金ETF (沪市)
]

HIGH_WINDOW        = 252   # 52周高点窗口 (交易日, A股一年约244个交易日)
MIN_HISTORY_DAYS   = 253   # 最少需要的历史数据天数 (252+1)
MAX_HOLDINGS       = 2     # 最大持仓数
REBALANCE_STEP     = 30    # 每 N 个交易日调仓一次 (与本地回测一致)
WARMUP_DAYS        = 180   # 预热期: 数据就绪前不交易
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
    g.etf_pool         = ETF_POOL
    g.high_window      = HIGH_WINDOW
    g.min_history_days = MIN_HISTORY_DAYS
    g.max_holdings     = MAX_HOLDINGS
    g.rebalance_step   = REBALANCE_STEP
    g.warmup_days      = WARMUP_DAYS
    g.day_counter      = 0

    # 用 run_daily 替代 handle_data (聚宽推荐)
    run_daily(daily_check, time='9:31')

    log.info('=' * 50)
    log.info('52周高点(52WH)因子 ETF轮动策略 初始化完成')
    log.info(f'ETF池: {len(g.etf_pool)}只')
    log.info(f'高点窗口: {g.high_window}天')
    log.info(f'最大持仓: {g.max_holdings}只')
    log.info(f'调仓周期: 每{g.rebalance_step}天')
    log.info(f'预热: {g.warmup_days}天')
    log.info('=' * 50)


# ============================================================
# 每日主逻辑
# ============================================================
def daily_check(context):
    """每日运行，仅在调仓日执行实际交易。"""
    g.day_counter += 1

    # 预热期: 数据就绪前不交易 (与本地回测 warmup=180 对齐)
    if g.day_counter < g.warmup_days:
        return

    # 只在调仓日执行
    if (g.day_counter - g.warmup_days) % g.rebalance_step != 0:
        return

    # ---------- 因子计算 & 排名 ----------
    scores = compute_52wh_scores(context, g.etf_pool)

    if not scores:
        log.warn('无有效52WH评分, 跳过调仓')
        return

    # 选52WH最高的前N只
    ranked = sorted(scores, key=lambda x: x['ratio'], reverse=True)
    selected = [item['symbol'] for item in ranked[:g.max_holdings]]

    # ---------- 调仓 ----------
    rebalance(context, selected)

    # ---------- 日志 ----------
    log.info(
        f'[调仓] day={g.day_counter} 选中: {selected} '
        '排名: ' + str([
            (r['symbol'], round(r['ratio'], 3), round(r['distance'], 3))
            for r in ranked
        ])
    )


# ============================================================
# 因子计算: 52WH = close / max(close[-252:])
# ============================================================
def compute_52wh_scores(context, etf_list):
    """计算每只ETF的52周高点距离因子值。

    ratio    = close / 过去252个交易日最高收盘价  (越接近1越贴近52周高点)
    distance = ratio - 1  (0=在52周高点, 负值=距高点越远)

    Returns:
        list[dict]: [{'symbol': ..., 'ratio': ..., 'distance': ...}, ...]
    """
    scores = []

    for symbol in etf_list:
        try:
            # 用 get_price 获取历史收盘价 (聚宽2.0推荐, 兼容性优于 attribute_history)
            # 前复权处理分红除息; dropna 丢弃停牌/未上市导致的 NaN 行
            df = get_price(
                symbol,
                end_date=context.current_dt,
                count=g.high_window + 1,
                frequency='daily',
                fields=['close'],
                skip_paused=True,
                fq='pre',
            )
            df = df.dropna()
        except Exception as e:
            log.debug(f'{symbol} 数据获取失败: {e}')
            continue

        if df is None or len(df) < g.high_window + 1:
            log.debug(
                f'{symbol} 数据不足: {len(df) if df is not None else 0}/'
                f'{g.high_window + 1} (上市时间可能不足252个交易日)'
            )
            continue

        closes = df['close'].values
        if len(closes) < g.high_window + 1:
            continue
        # 宽松校验: 只要求有效价格(>0 且有限)足够多, 允许个别停牌导致的 NaN 已被 dropna 剔除
        valid = [p for p in closes if p > 0 and np.isfinite(p)]
        if len(valid) < g.high_window + 1:
            log.debug(f'{symbol} 有效价格不足: {len(valid)}/{g.high_window + 1}')
            continue
        closes = np.asarray(valid)

        # 52周高点 = 过去252个交易日的最高收盘价
        high_252 = np.max(closes[-g.high_window:])
        if high_252 <= 0:
            continue

        # 当前价格距52周高点的比率
        ratio = float(closes[-1] / high_252)
        distance = ratio - 1.0

        if np.isfinite(ratio):
            scores.append({
                'symbol': symbol,
                'ratio': ratio,
                'distance': distance,
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
