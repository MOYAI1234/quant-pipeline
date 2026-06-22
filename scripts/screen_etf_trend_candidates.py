import argparse
import itertools
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.runner import RotationBacktestRunner
from research.etf_dual_momentum import load_rotation_csv
from strategy.base import BaseStrategy


@dataclass(frozen=True)
class TrendCandidateConfig:
    name: str
    market_proxy: str
    rebalance_interval: int
    max_holdings: int
    max_weight_per_etf: float
    fast_window: int
    slow_window: int
    trend_window: int
    market_trend_window: int
    vol_window: int
    drawdown_window: int
    max_recent_drawdown: float
    require_own_trend: bool
    use_market_filter: bool
    weight_mode: str
    target_exposure: float

    @property
    def required_prices(self) -> int:
        return max(
            self.fast_window + 1,
            self.slow_window + 1,
            self.trend_window,
            self.market_trend_window,
            self.vol_window + 1,
            self.drawdown_window,
        )


class ETFTrendCandidateStrategy(BaseStrategy):
    """ETF 主线趋势/相对强弱候选的本地筛选策略。"""

    def __init__(self, etf_pool: list[str], candidate_config: TrendCandidateConfig):
        super().__init__({
            'name': candidate_config.name,
            'symbol': etf_pool[0],
            'etf_pool': etf_pool,
        })
        self.etf_pool = etf_pool
        self.candidate_config = candidate_config
        self.current_targets = []
        self.days_since_rebalance = candidate_config.rebalance_interval
        self.evaluation_count = 0
        self.rebalance_count = 0
        self.selected_history = []
        self.regime_counts = Counter()
        self.rejection_reasons = Counter()

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        portfolio = portfolio or {}
        self.evaluation_count += 1
        self.days_since_rebalance += 1

        if not self._market_ok(data):
            if self.current_targets:
                self.current_targets = []
                self.rebalance_count += 1
                self.days_since_rebalance = 0
                self.regime_counts.update(['market_weak_clear'])
                return _target_weight_signals(data, portfolio, [], {}, '市场趋势转弱清仓')
            self.regime_counts.update(['market_weak'])
            return []

        if self.days_since_rebalance < self.candidate_config.rebalance_interval:
            self.regime_counts.update(['hold_interval'])
            return []

        ranked = self._rank_candidates(data)
        selected = [item['symbol'] for item in ranked[: self.candidate_config.max_holdings]]
        weights = _weights(
            [item for item in ranked if item['symbol'] in selected],
            self.candidate_config,
        )

        if selected == self.current_targets:
            self.days_since_rebalance = 0
            self.regime_counts.update(['unchanged'])
            return []

        self.current_targets = selected
        self.days_since_rebalance = 0
        self.rebalance_count += 1
        self.selected_history.append({
            'date': data.get('_date', ''),
            'selected': list(selected),
        })
        self.regime_counts.update(['risk_on' if selected else 'cash'])
        return _target_weight_signals(
            data,
            portfolio,
            selected,
            weights,
            self.candidate_config.name,
        )

    def calc_position_size(self, capital: float, price: float) -> int:
        if price <= 0:
            return 0
        return int(capital / price / 100) * 100

    def _market_ok(self, data: dict) -> bool:
        if not self.candidate_config.use_market_filter:
            return True
        bar = data.get(self.candidate_config.market_proxy) or {}
        prices = _prices(bar)
        window = self.candidate_config.market_trend_window
        if len(prices) < window:
            self.rejection_reasons.update(['market_insufficient_history'])
            return False
        return prices[-1] >= sum(prices[-window:]) / window

    def _rank_candidates(self, data: dict) -> list[dict]:
        ranked = []
        for symbol in self.etf_pool:
            item, reason = self._factor(symbol, data.get(symbol) or {})
            if item is None:
                self.rejection_reasons.update([reason])
            else:
                ranked.append(item)
        return sorted(ranked, key=lambda item: item['score'], reverse=True)

    def _factor(self, symbol: str, bar: dict) -> tuple[dict | None, str]:
        config = self.candidate_config
        prices = _prices(bar)
        if len(prices) < config.required_prices:
            return None, 'insufficient_history'
        latest = prices[-1]
        fast_base = prices[-config.fast_window - 1]
        slow_base = prices[-config.slow_window - 1]
        trend_ma = sum(prices[-config.trend_window:]) / config.trend_window
        recent_high = max(prices[-config.drawdown_window:])
        if latest <= 0 or fast_base <= 0 or slow_base <= 0 or trend_ma <= 0:
            return None, 'invalid_factor'

        fast_momentum = latest / fast_base - 1.0
        slow_momentum = latest / slow_base - 1.0
        recent_drawdown = latest / recent_high - 1.0
        if fast_momentum <= 0 or slow_momentum <= 0:
            return None, 'non_positive_momentum'
        if config.require_own_trend and latest < trend_ma:
            return None, 'below_own_trend'
        if recent_drawdown <= -config.max_recent_drawdown:
            return None, 'recent_drawdown_too_deep'

        volatility = _std(_returns(prices[-config.vol_window - 1:]))
        if volatility <= 0:
            return None, 'invalid_volatility'

        score = fast_momentum * 0.45 + slow_momentum * 0.45
        score += recent_drawdown * 0.20
        score -= volatility * 2.0
        return {
            'symbol': symbol,
            'score': score,
            'fast_momentum': fast_momentum,
            'slow_momentum': slow_momentum,
            'recent_drawdown': recent_drawdown,
            'volatility': volatility,
        }, ''


def main() -> int:
    parser = argparse.ArgumentParser(description='筛选 ETF 趋势/相对强弱候选策略')
    parser.add_argument('--history', required=True, help='rotation CSV 路径')
    parser.add_argument('--etf-pool', required=True, help='逗号分隔 ETF 池')
    parser.add_argument('--top', type=int, default=12, help='输出前 N 个候选')
    parser.add_argument(
        '--sort-by',
        choices=['drawdown', 'annual'],
        default='drawdown',
        help='排序口径：drawdown=低回撤优先，annual=高年化优先',
    )
    parser.add_argument('--max-drawdown', type=float, help='只输出最大回撤不超过该比例的候选')
    parser.add_argument('--eval-start-date', help='只从该日期开始评估，格式 YYYY-MM-DD')
    parser.add_argument('--eval-end-date', help='只评估到该日期，格式 YYYY-MM-DD')
    parser.add_argument('--initial-capital', type=float, default=100000)
    parser.add_argument('--commission-rate', type=float, default=0.0003)
    parser.add_argument('--min-commission', type=float, default=5)
    parser.add_argument('--slippage-rate', type=float, default=0.001)
    parser.add_argument('--max-volume-participation', type=float, default=0.05)
    args = parser.parse_args()

    history = _filter_history(
        load_rotation_csv(args.history),
        args.eval_start_date,
        args.eval_end_date,
    )
    etf_pool = _parse_symbols(args.etf_pool)
    results = []
    for candidate_config in _candidate_configs(etf_pool[0]):
        strategy = ETFTrendCandidateStrategy(etf_pool, candidate_config)
        runner = RotationBacktestRunner(strategy, _account_config(args))
        result = runner.run(history)
        results.append(_summary(result, runner.strategy))

    if args.max_drawdown is not None:
        results = [
            item for item in results
            if item['max_drawdown'] <= args.max_drawdown
        ]
    if args.sort_by == 'annual':
        results.sort(key=lambda item: (-item['annual_return'], item['max_drawdown']))
    else:
        results.sort(key=lambda item: (item['max_drawdown'], -item['annual_return']))
    print(_render_table(results[: args.top]))
    return 0


def _candidate_configs(market_proxy: str) -> list[TrendCandidateConfig]:
    configs = []
    for (
        rebalance_interval,
        max_holdings,
        fast_window,
        slow_window,
        trend_window,
        market_trend_window,
        require_own_trend,
        use_market_filter,
        weight_mode,
        target_exposure,
    ) in itertools.product(
        [20, 40, 60],
        [1, 2],
        [60, 90],
        [120, 180],
        [120, 200],
        [160, 200],
        [True, False],
        [True],
        ['equal', 'inverse_vol'],
        [0.8, 1.0],
    ):
        if slow_window <= fast_window:
            continue
        name = (
            f"ETF-SCREEN interval={rebalance_interval} holdings={max_holdings} "
            f"fast={fast_window} slow={slow_window} trend={trend_window} "
            f"market={market_trend_window} ownTrend={require_own_trend} "
            f"weight={weight_mode} exposure={target_exposure}"
        )
        configs.append(TrendCandidateConfig(
            name=name,
            market_proxy=market_proxy,
            rebalance_interval=rebalance_interval,
            max_holdings=max_holdings,
            max_weight_per_etf=1.0 if max_holdings == 1 else 0.50,
            fast_window=fast_window,
            slow_window=slow_window,
            trend_window=trend_window,
            market_trend_window=market_trend_window,
            vol_window=60,
            drawdown_window=60,
            max_recent_drawdown=0.18,
            require_own_trend=require_own_trend,
            use_market_filter=use_market_filter,
            weight_mode=weight_mode,
            target_exposure=target_exposure,
        ))
    return configs


def _account_config(args) -> dict:
    return {
        'initial_capital': args.initial_capital,
        'commission_rate': args.commission_rate,
        'min_commission': args.min_commission,
        'slippage_rate': args.slippage_rate,
        'max_volume_participation': args.max_volume_participation,
        'allow_partial_fills': True,
    }


def _filter_history(history: list, start_date: str | None, end_date: str | None) -> list:
    filtered = []
    for snapshot in history:
        date = snapshot.get('date', snapshot.get('timestamp', ''))
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        filtered.append(snapshot)
    if not filtered:
        raise ValueError('过滤后没有可评估历史')
    return filtered


def _summary(result: dict, strategy: ETFTrendCandidateStrategy) -> dict:
    years = _years(result['start_date'], result['end_date'])
    total_return = result['total_return']
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    return {
        'name': strategy.candidate_config.name,
        'annual_return': annual_return,
        'total_return': total_return,
        'max_drawdown': result['max_drawdown'],
        'trade_count': result['trade_count'],
        'turnover_ratio': result['turnover_ratio'],
        'commission_ratio': result['commission_ratio'],
        'final_value': result['final_value'],
        'regime_counts': dict(strategy.regime_counts),
        'rejection_reasons': dict(strategy.rejection_reasons),
    }


def _render_table(results: list[dict]) -> str:
    lines = [
        '| 排名 | 年化 | 总收益 | 最大回撤 | 交易次数 | 成交额/初始资金 | 费用/初始资金 | 候选 |',
        '|---:|---:|---:|---:|---:|---:|---:|---|',
    ]
    for index, item in enumerate(results, start=1):
        lines.append(
            '| {rank} | {annual:.2%} | {total:.2%} | {drawdown:.2%} | '
            '{trades} | {turnover:.2%} | {commission:.4%} | `{name}` |'.format(
                rank=index,
                annual=item['annual_return'],
                total=item['total_return'],
                drawdown=item['max_drawdown'],
                trades=item['trade_count'],
                turnover=item['turnover_ratio'],
                commission=item['commission_ratio'],
                name=item['name'],
            )
        )
    return '\n'.join(lines)


def _target_weight_signals(
    data: dict,
    portfolio: dict,
    selected: list[str],
    weights: dict[str, float],
    reason: str,
) -> list[dict]:
    signals = []
    positions = portfolio.get('positions', {})
    signal_time = data.get('_date')
    trading_costs = portfolio.get('trading_costs', {})
    min_commission = trading_costs.get('min_commission', 0)
    buy_commission_rate = trading_costs.get('buy_commission_rate', 0)
    sell_commission_rate = trading_costs.get('sell_commission_rate', 0)

    cash = float(portfolio.get('capital', 0) or 0)
    for symbol, position in positions.items():
        shares = int(position.get('shares', 0) // 100) * 100
        if shares <= 0 or symbol in selected:
            continue
        price = _price(symbol, data, position)
        if price <= 0:
            continue
        amount = shares * price
        signals.append({
            'action': 'sell',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'amount': amount,
            'reason': reason + ' 卖出',
            'timestamp': signal_time,
        })
        cash += _estimated_sell_proceeds(
            amount,
            sell_commission_rate,
            min_commission,
        )

    total_value = float(portfolio.get('total_value', 0) or 0)
    for symbol in selected:
        if symbol not in data:
            continue
        price = _price(symbol, data, positions.get(symbol, {}))
        if price <= 0:
            continue
        current_shares = positions.get(symbol, {}).get('shares', 0)
        current_value = current_shares * price
        target_value = total_value * weights.get(symbol, 0)
        delta = target_value - current_value
        if abs(delta) < max(min_commission, price * 100):
            continue
        if delta < 0:
            shares = int(abs(delta) / price / 100) * 100
            shares = min(shares, int(current_shares // 100) * 100)
            if shares > 0:
                signals.append({
                    'action': 'sell',
                    'symbol': symbol,
                    'price': price,
                    'shares': shares,
                    'amount': shares * price,
                    'reason': reason + ' 降仓',
                    'timestamp': signal_time,
                })
            continue

        budget = min(delta, cash)
        max_notional = min(
            budget / (1 + buy_commission_rate),
            budget - min_commission,
        )
        shares = int(max_notional / price / 100) * 100 if max_notional > 0 else 0
        if shares <= 0:
            continue
        amount = shares * price
        signals.append({
            'action': 'buy',
            'symbol': symbol,
            'price': price,
            'shares': shares,
            'amount': amount,
            'reason': reason + ' 买入',
            'timestamp': signal_time,
        })
        cash = max(cash - amount * (1 + buy_commission_rate) - min_commission, 0)

    return signals


def _estimated_sell_proceeds(
    amount: float,
    sell_commission_rate: float,
    min_commission: float,
) -> float:
    commission = max(amount * sell_commission_rate, min_commission)
    return max(amount - commission, 0)


def _weights(items: list[dict], config: TrendCandidateConfig) -> dict[str, float]:
    if not items:
        return {}
    if config.weight_mode == 'equal':
        raw = {item['symbol']: 1 / len(items) for item in items}
    elif config.weight_mode == 'inverse_vol':
        total = sum(1 / item['volatility'] for item in items)
        raw = {
            item['symbol']: (1 / item['volatility']) / total
            for item in items
        }
    else:
        raise ValueError(f'unknown weight_mode: {config.weight_mode}')
    return {
        symbol: min(weight * config.target_exposure, config.max_weight_per_etf)
        for symbol, weight in raw.items()
    }


def _prices(bar: dict) -> list[float]:
    prices = []
    for value in bar.get('prices') or []:
        price = float(value)
        if price > 0:
            prices.append(price)
    return prices


def _returns(prices: list[float]) -> list[float]:
    return [
        prices[index] / prices[index - 1] - 1.0
        for index in range(1, len(prices))
        if prices[index - 1] > 0
    ]


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _price(symbol: str, data: dict, position: dict) -> float:
    if isinstance(data.get(symbol), dict):
        price = data[symbol].get('price', 0)
        if price > 0:
            return price
    return position.get('current_price', position.get('avg_price', 0))


def _years(start_date: str, end_date: str) -> float:
    from datetime import date

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return max((end - start).days / 365.25, 0)


def _parse_symbols(value: str) -> list[str]:
    symbols = [symbol.strip() for symbol in value.split(',') if symbol.strip()]
    if not symbols:
        raise ValueError('--etf-pool 不能为空')
    return symbols


if __name__ == '__main__':
    raise SystemExit(main())
