import argparse
import csv
import itertools
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.runner import RotationBacktestRunner
from research.candidate_gates import CandidateGateConfig, evaluate_candidate
from research.etf_dual_momentum import load_rotation_csv
from strategy.base import BaseStrategy


@dataclass(frozen=True)
class TrendCandidateConfig:
    name: str
    family: str
    market_proxy: str
    rebalance_interval: int
    max_holdings: int
    max_weight_per_etf: float
    fast_window: int
    slow_window: int
    trend_window: int
    market_trend_window: int
    breadth_window: int
    breadth_threshold: float
    vol_window: int
    drawdown_window: int
    max_recent_drawdown: float
    require_own_trend: bool
    use_market_filter: bool
    use_breadth_filter: bool
    weight_mode: str
    target_exposure: float
    exposure_mode: str
    min_switch_score_gap: float

    @property
    def required_prices(self) -> int:
        windows = [
            self.fast_window + 1,
            self.slow_window + 1,
            self.trend_window,
            self.market_trend_window,
            self.vol_window + 1,
            self.drawdown_window,
        ]
        if self.use_breadth_filter:
            windows.append(self.breadth_window)
        return max(windows)


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
        self.pending_targets = None
        self.pending_weights = {}
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
        actual_positions = _actual_position_symbols(portfolio)

        if not self._market_ok(data):
            if actual_positions:
                self.rebalance_count += 1
                self.days_since_rebalance = 0
                self.pending_targets = []
                self.pending_weights = {}
                self.regime_counts.update(['market_weak_clear'])
                return _target_weight_signals(data, portfolio, [], {}, '市场趋势转弱清仓')
            self.current_targets = []
            self.pending_targets = None
            self.pending_weights = {}
            self.regime_counts.update(['market_weak'])
            return []

        retry_pending = self.pending_targets is not None
        if retry_pending:
            return self._retry_pending_targets(data, portfolio)

        if (
            self.days_since_rebalance < self.candidate_config.rebalance_interval
        ):
            self.regime_counts.update(['hold_interval'])
            return []

        ranked = self._rank_candidates(data)
        selected = _stabilized_selection(
            ranked,
            actual_positions,
            self.candidate_config.max_holdings,
            self.candidate_config.min_switch_score_gap,
        )
        ranked_by_symbol = {item['symbol']: item for item in ranked}
        target_exposure = _target_exposure(data, self.etf_pool, self.candidate_config)
        weights = _weights(
            [
                ranked_by_symbol[symbol]
                for symbol in selected
                if symbol in ranked_by_symbol
            ],
            self.candidate_config,
            target_exposure,
        )
        if selected and target_exposure < self.candidate_config.target_exposure:
            self.regime_counts.update(['exposure_reduced'])

        signals = _target_weight_signals(
            data,
            portfolio,
            selected,
            weights,
            self.candidate_config.name,
        )
        if not signals and _portfolio_matches_targets(
            data,
            portfolio,
            selected,
            weights,
        ):
            self.current_targets = selected
            self.pending_targets = None
            self.pending_weights = {}
            self.days_since_rebalance = 0
            self.regime_counts.update(['unchanged'])
            return []

        self.pending_targets = selected
        self.pending_weights = dict(weights)
        self.days_since_rebalance = self.candidate_config.rebalance_interval
        self.rebalance_count += 1
        self.selected_history.append({
            'date': data.get('_date', ''),
            'selected': list(selected),
        })
        self.regime_counts.update(['risk_on' if selected else 'cash'])
        return signals

    def _retry_pending_targets(self, data: dict, portfolio: dict) -> list:
        selected = list(self.pending_targets or [])
        weights = dict(self.pending_weights)
        signals = _target_weight_signals(
            data,
            portfolio,
            selected,
            weights,
            self.candidate_config.name,
        )
        if not signals and _portfolio_matches_targets(
            data,
            portfolio,
            selected,
            weights,
        ):
            self.current_targets = selected
            self.pending_targets = None
            self.pending_weights = {}
            self.days_since_rebalance = 0
            self.regime_counts.update(['unchanged'])
            return []
        self.days_since_rebalance = self.candidate_config.rebalance_interval
        self.regime_counts.update(['pending_retry'])
        return signals

    def calc_position_size(self, capital: float, price: float) -> int:
        if price <= 0:
            return 0
        return int(capital / price / 100) * 100

    def _market_ok(self, data: dict) -> bool:
        config = self.candidate_config
        if config.use_market_filter:
            bar = data.get(config.market_proxy) or {}
            prices = _prices(bar)
            window = config.market_trend_window
            if len(prices) < window:
                self.rejection_reasons.update(['market_insufficient_history'])
                return False
            if prices[-1] < sum(prices[-window:]) / window:
                self.rejection_reasons.update(['market_trend_weak'])
                return False
        if config.use_breadth_filter:
            breadth = _trend_breadth(data, self.etf_pool, config.breadth_window)
            if breadth is None:
                self.rejection_reasons.update(['breadth_insufficient_history'])
                return False
            if breadth < config.breadth_threshold:
                self.rejection_reasons.update(['breadth_weak'])
                return False
        return True

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
    parser.add_argument(
        '--gate-status',
        choices=['all', 'pass', 'watchlist', 'reject'],
        default='all',
        help='按自动准入结论过滤输出',
    )
    parser.add_argument(
        '--factor-family',
        choices=[
            'all',
            'daily_core_guard',
            'swing_trend_guard',
            'adaptive_exposure_guard',
        ],
        default='all',
        help='只运行指定 ETF 因子族，默认运行全部',
    )
    parser.add_argument('--gate-min-annual-return', type=float, default=0.06)
    parser.add_argument('--gate-max-drawdown', type=float, default=0.15)
    parser.add_argument('--gate-max-annual-turnover', type=float, default=8.0)
    parser.add_argument('--gate-max-annual-fee', type=float, default=0.005)
    parser.add_argument('--gate-max-trades-per-day', type=int, default=2)
    parser.add_argument('--gate-min-trades', type=int, default=4)
    parser.add_argument('--gate-max-cash-days', type=float, default=0.80)
    parser.add_argument('--eval-start-date', help='只从该日期开始评估，格式 YYYY-MM-DD')
    parser.add_argument('--eval-end-date', help='只评估到该日期，格式 YYYY-MM-DD')
    parser.add_argument('--initial-capital', type=float, default=100000)
    parser.add_argument('--commission-rate', type=float, default=0.0003)
    parser.add_argument('--min-commission', type=float, default=5)
    parser.add_argument('--slippage-rate', type=float, default=0.001)
    parser.add_argument('--max-volume-participation', type=float, default=0.05)
    parser.add_argument(
        '--results-output',
        help='候选明细输出路径，支持 .json 或 .csv，内容遵循当前过滤条件但不受 --top 限制',
    )
    parser.add_argument(
        '--summary-output',
        help='筛选总览输出路径，支持 .json 或 .csv，统计基于全部已评估候选',
    )
    args = parser.parse_args()

    history = _filter_history(
        load_rotation_csv(args.history),
        args.eval_start_date,
        args.eval_end_date,
    )
    etf_pool = _parse_symbols(args.etf_pool)
    gate_config = _gate_config(args)
    results = []
    for candidate_config in _candidate_configs(etf_pool[0], args.factor_family):
        strategy = ETFTrendCandidateStrategy(etf_pool, candidate_config)
        runner = RotationBacktestRunner(strategy, _account_config(args))
        result = runner.run(history)
        results.append(_summary(result, runner.strategy, gate_config))

    _sort_results(results, args.sort_by)
    visible_results = _visible_results(results, args)
    summary = _screening_summary(results, visible_results)
    if args.results_output:
        _write_candidate_results(args.results_output, visible_results)
        print(f'候选明细: {args.results_output}')
    if args.summary_output:
        _write_screening_summary(args.summary_output, summary)
        print(f'筛选总览: {args.summary_output}')
    print(_render_table(visible_results[: args.top]))
    return 0


def _candidate_configs(
    market_proxy: str,
    factor_family: str = 'all',
) -> list[TrendCandidateConfig]:
    configs = []
    profiles = [
        {
            'family': 'daily_core_guard',
            'rebalance_intervals': [1, 5],
            'max_holdings': [1, 2],
            'fast_windows': [20, 40],
            'slow_windows': [60, 90],
            'trend_windows': [80],
            'market_trend_windows': [120],
            'breadth_windows': [80],
            'breadth_thresholds': [0.50, 0.60],
            'max_recent_drawdowns': [0.12],
            'require_own_trends': [True],
            'weight_modes': ['equal', 'inverse_vol'],
            'target_exposures': [0.50, 0.70],
            'exposure_modes': ['static'],
            'min_switch_score_gaps': [0.01, 0.02],
        },
        {
            'family': 'swing_trend_guard',
            'rebalance_intervals': [10, 20],
            'max_holdings': [1, 2],
            'fast_windows': [40, 60],
            'slow_windows': [120, 180],
            'trend_windows': [120, 200],
            'market_trend_windows': [160, 200],
            'breadth_windows': [120],
            'breadth_thresholds': [0.50],
            'max_recent_drawdowns': [0.16],
            'require_own_trends': [True, False],
            'weight_modes': ['equal', 'inverse_vol'],
            'target_exposures': [0.70, 0.90],
            'exposure_modes': ['static'],
            'min_switch_score_gaps': [0.01],
        },
        {
            'family': 'adaptive_exposure_guard',
            'rebalance_intervals': [10, 20],
            'max_holdings': [1],
            'fast_windows': [40, 60],
            'slow_windows': [120, 180],
            'trend_windows': [120],
            'market_trend_windows': [160, 200],
            'breadth_windows': [120],
            'breadth_thresholds': [0.50],
            'max_recent_drawdowns': [0.16],
            'require_own_trends': [True],
            'weight_modes': ['equal'],
            'target_exposures': [0.80, 1.00],
            'exposure_modes': ['trend_strength'],
            'min_switch_score_gaps': [0.01],
        },
    ]
    for profile in profiles:
        if factor_family != 'all' and profile['family'] != factor_family:
            continue
        configs.extend(_profile_candidate_configs(market_proxy, profile))
    return configs


def _profile_candidate_configs(
    market_proxy: str,
    profile: dict,
) -> list[TrendCandidateConfig]:
    configs = []
    for (
        rebalance_interval,
        max_holdings,
        fast_window,
        slow_window,
        trend_window,
        market_trend_window,
        breadth_window,
        breadth_threshold,
        max_recent_drawdown,
        require_own_trend,
        weight_mode,
        target_exposure,
        exposure_mode,
        min_switch_score_gap,
    ) in itertools.product(
        profile['rebalance_intervals'],
        profile['max_holdings'],
        profile['fast_windows'],
        profile['slow_windows'],
        profile['trend_windows'],
        profile['market_trend_windows'],
        profile['breadth_windows'],
        profile['breadth_thresholds'],
        profile['max_recent_drawdowns'],
        profile['require_own_trends'],
        profile['weight_modes'],
        profile['target_exposures'],
        profile['exposure_modes'],
        profile['min_switch_score_gaps'],
    ):
        if slow_window <= fast_window:
            continue
        name = (
            f"ETF-SCREEN family={profile['family']} "
            f"interval={rebalance_interval} holdings={max_holdings} "
            f"fast={fast_window} slow={slow_window} trend={trend_window} "
            f"market={market_trend_window} breadth={breadth_window}/"
            f"{breadth_threshold:.0%} ownTrend={require_own_trend} "
            f"weight={weight_mode} exposure={target_exposure} "
            f"exposureMode={exposure_mode} "
            f"switchGap={min_switch_score_gap}"
        )
        configs.append(TrendCandidateConfig(
            name=name,
            family=profile['family'],
            market_proxy=market_proxy,
            rebalance_interval=rebalance_interval,
            max_holdings=max_holdings,
            max_weight_per_etf=1.0 if max_holdings == 1 else 0.50,
            fast_window=fast_window,
            slow_window=slow_window,
            trend_window=trend_window,
            market_trend_window=market_trend_window,
            breadth_window=breadth_window,
            breadth_threshold=breadth_threshold,
            vol_window=60,
            drawdown_window=60,
            max_recent_drawdown=max_recent_drawdown,
            require_own_trend=require_own_trend,
            use_market_filter=True,
            use_breadth_filter=True,
            weight_mode=weight_mode,
            target_exposure=target_exposure,
            exposure_mode=exposure_mode,
            min_switch_score_gap=min_switch_score_gap,
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


def _gate_config(args) -> CandidateGateConfig:
    return CandidateGateConfig(
        min_annual_return=args.gate_min_annual_return,
        max_drawdown=args.gate_max_drawdown,
        max_annual_turnover=args.gate_max_annual_turnover,
        max_annual_commission_ratio=args.gate_max_annual_fee,
        max_trades_per_day=args.gate_max_trades_per_day,
        min_trade_count=args.gate_min_trades,
        max_cash_day_ratio=args.gate_max_cash_days,
    )


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


def _summary(
    result: dict,
    strategy: ETFTrendCandidateStrategy,
    gate_config: CandidateGateConfig | None = None,
) -> dict:
    years = _years(result['start_date'], result['end_date'])
    total_return = result['total_return']
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    decision = evaluate_candidate({
        **result,
        'years': years,
        'annual_return': annual_return,
    }, gate_config)
    return {
        'name': strategy.candidate_config.name,
        'family': strategy.candidate_config.family,
        'annual_return': annual_return,
        'total_return': total_return,
        'max_drawdown': result['max_drawdown'],
        'trade_count': result['trade_count'],
        'turnover_ratio': result['turnover_ratio'],
        'commission_ratio': result['commission_ratio'],
        'annual_turnover': decision.annual_turnover,
        'annual_commission_ratio': decision.annual_commission_ratio,
        'max_daily_trades': decision.max_daily_trades,
        'cash_day_ratio': decision.cash_day_ratio,
        'gate_status': decision.status,
        'gate_reasons': list(decision.reasons),
        'final_value': result['final_value'],
        'regime_counts': dict(strategy.regime_counts),
        'rejection_reasons': dict(strategy.rejection_reasons),
    }


def _render_table(results: list[dict]) -> str:
    lines = [
        '| 排名 | 准入 | 因子族 | 年化 | 最大回撤 | 年化换手 | 年化费用 | 单日最多成交 | 纯现金日 | 候选 |',
        '|---:|---|---|---:|---:|---:|---:|---:|---:|---|',
    ]
    for index, item in enumerate(results, start=1):
        lines.append(
            '| {rank} | {status} | {family} | {annual:.2%} | {drawdown:.2%} | '
            '{annual_turnover:.2%} | {annual_fee:.4%} | {daily_trades} | '
            '{cash_days:.2%} | `{name}` |'.format(
                rank=index,
                status=item['gate_status'],
                family=item['family'],
                annual=item['annual_return'],
                drawdown=item['max_drawdown'],
                annual_turnover=item['annual_turnover'],
                annual_fee=item['annual_commission_ratio'],
                daily_trades=item['max_daily_trades'],
                cash_days=item['cash_day_ratio'],
                name=item['name'],
            )
        )
        if item['gate_status'] != 'PASS':
            lines.append(
                f"|  | 原因 |  |  |  |  |  |  |  | {'；'.join(item['gate_reasons'])} |"
            )
    return '\n'.join(lines)


def _sort_results(results: list[dict], sort_by: str) -> None:
    status_rank = {'PASS': 0, 'WATCHLIST': 1, 'REJECT': 2}
    if sort_by == 'annual':
        results.sort(key=lambda item: (
            status_rank[item['gate_status']],
            -item['annual_return'],
            item['max_drawdown'],
        ))
        return
    results.sort(key=lambda item: (
        status_rank[item['gate_status']],
        item['max_drawdown'],
        -item['annual_return'],
    ))


def _visible_results(results: list[dict], args: argparse.Namespace) -> list[dict]:
    visible = list(results)
    if args.max_drawdown is not None:
        visible = [
            item for item in visible
            if item['max_drawdown'] <= args.max_drawdown
        ]
    if args.gate_status != 'all':
        expected_status = args.gate_status.upper()
        visible = [
            item for item in visible
            if item['gate_status'] == expected_status
        ]
    return visible


def _screening_summary(
    results: list[dict],
    visible_results: list[dict] | None = None,
) -> dict:
    visible_results = visible_results if visible_results is not None else results
    gate_reason_counts = Counter()
    rejection_reason_counts = Counter()
    family_status_counts = {}
    for item in results:
        gate_reason_counts.update(item.get('gate_reasons', []))
        rejection_reason_counts.update(item.get('rejection_reasons', {}))
        family = item['family']
        family_status_counts.setdefault(family, Counter())
        family_status_counts[family].update([item['gate_status']])

    return {
        'evaluated_candidates': len(results),
        'visible_candidates': len(visible_results),
        'status_counts': dict(Counter(item['gate_status'] for item in results)),
        'family_counts': dict(Counter(item['family'] for item in results)),
        'family_status_counts': {
            family: dict(counts)
            for family, counts in family_status_counts.items()
        },
        'gate_reason_counts': dict(gate_reason_counts),
        'rejection_reason_counts': dict(rejection_reason_counts),
        'best_by_drawdown': _best_candidate(results, 'drawdown'),
        'best_by_annual': _best_candidate(results, 'annual'),
    }


def _best_candidate(results: list[dict], metric: str) -> dict | None:
    if not results:
        return None
    if metric == 'annual':
        item = max(results, key=lambda value: value['annual_return'])
    elif metric == 'drawdown':
        item = min(results, key=lambda value: value['max_drawdown'])
    else:
        raise ValueError(f'unknown best candidate metric: {metric}')
    return {
        'name': item['name'],
        'family': item['family'],
        'gate_status': item['gate_status'],
        'annual_return': item['annual_return'],
        'max_drawdown': item['max_drawdown'],
        'annual_turnover': item['annual_turnover'],
        'annual_commission_ratio': item['annual_commission_ratio'],
        'cash_day_ratio': item['cash_day_ratio'],
    }


def _write_candidate_results(path: str, results: list[dict]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix == '.json':
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return output_path
    if suffix == '.csv':
        _write_candidate_results_csv(output_path, results)
        return output_path
    raise ValueError('--results-output 仅支持 .json 或 .csv')


def _write_candidate_results_csv(path: Path, results: list[dict]) -> None:
    fieldnames = [
        'name',
        'family',
        'gate_status',
        'annual_return',
        'total_return',
        'max_drawdown',
        'trade_count',
        'turnover_ratio',
        'commission_ratio',
        'annual_turnover',
        'annual_commission_ratio',
        'max_daily_trades',
        'cash_day_ratio',
        'final_value',
        'gate_reasons',
        'regime_counts',
        'rejection_reasons',
    ]
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in results:
            writer.writerow(_candidate_csv_row(item))


def _candidate_csv_row(item: dict) -> dict:
    return {
        'name': item['name'],
        'family': item['family'],
        'gate_status': item['gate_status'],
        'annual_return': item['annual_return'],
        'total_return': item['total_return'],
        'max_drawdown': item['max_drawdown'],
        'trade_count': item['trade_count'],
        'turnover_ratio': item['turnover_ratio'],
        'commission_ratio': item['commission_ratio'],
        'annual_turnover': item['annual_turnover'],
        'annual_commission_ratio': item['annual_commission_ratio'],
        'max_daily_trades': item['max_daily_trades'],
        'cash_day_ratio': item['cash_day_ratio'],
        'final_value': item['final_value'],
        'gate_reasons': ';'.join(item.get('gate_reasons', [])),
        'regime_counts': json.dumps(
            item.get('regime_counts', {}),
            ensure_ascii=False,
            sort_keys=True,
        ),
        'rejection_reasons': json.dumps(
            item.get('rejection_reasons', {}),
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _write_screening_summary(path: str, summary: dict) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix == '.json':
        output_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return output_path
    if suffix == '.csv':
        _write_screening_summary_csv(output_path, summary)
        return output_path
    raise ValueError('--summary-output 仅支持 .json 或 .csv')


def _write_screening_summary_csv(path: Path, summary: dict) -> None:
    rows = _summary_csv_rows(summary)
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(
            file,
            fieldnames=['section', 'family', 'key', 'value'],
        )
        writer.writeheader()
        writer.writerows(rows)


def _summary_csv_rows(summary: dict) -> list[dict]:
    rows = [
        {
            'section': 'total',
            'family': 'all',
            'key': 'evaluated_candidates',
            'value': summary['evaluated_candidates'],
        },
        {
            'section': 'total',
            'family': 'all',
            'key': 'visible_candidates',
            'value': summary['visible_candidates'],
        },
    ]
    for section in ['status_counts', 'family_counts']:
        for key, value in summary.get(section, {}).items():
            rows.append({
                'section': section,
                'family': 'all',
                'key': key,
                'value': value,
            })
    for family, status_counts in summary.get('family_status_counts', {}).items():
        for status, value in status_counts.items():
            rows.append({
                'section': 'family_status_counts',
                'family': family,
                'key': status,
                'value': value,
            })
    for section in ['gate_reason_counts', 'rejection_reason_counts']:
        for key, value in summary.get(section, {}).items():
            rows.append({
                'section': section,
                'family': 'all',
                'key': key,
                'value': value,
            })
    for section in ['best_by_drawdown', 'best_by_annual']:
        candidate = summary.get(section)
        if not candidate:
            continue
        rows.append({
            'section': section,
            'family': candidate['family'],
            'key': 'name',
            'value': candidate['name'],
        })
        for key in [
            'gate_status',
            'annual_return',
            'max_drawdown',
            'annual_turnover',
            'annual_commission_ratio',
            'cash_day_ratio',
        ]:
            rows.append({
                'section': section,
                'family': candidate['family'],
                'key': key,
                'value': candidate[key],
            })
    return rows


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
                amount = shares * price
                signals.append({
                    'action': 'sell',
                    'symbol': symbol,
                    'price': price,
                    'shares': shares,
                    'amount': amount,
                    'reason': reason + ' 降仓',
                    'timestamp': signal_time,
                })
                cash += _estimated_sell_proceeds(
                    amount,
                    sell_commission_rate,
                    min_commission,
                )
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


def _actual_position_symbols(portfolio: dict) -> list[str]:
    positions = portfolio.get('positions', {})
    return sorted(
        symbol
        for symbol, position in positions.items()
        if position.get('shares', 0) > 0
    )


def _portfolio_matches_targets(
    data: dict,
    portfolio: dict,
    selected: list[str],
    weights: dict[str, float],
) -> bool:
    positions = portfolio.get('positions', {})
    selected_symbols = set(selected)
    actual_symbols = set(_actual_position_symbols(portfolio))
    if actual_symbols - selected_symbols:
        return False

    total_value = float(portfolio.get('total_value', 0) or 0)
    if total_value <= 0:
        return not selected_symbols and not actual_symbols

    min_commission = portfolio.get('trading_costs', {}).get('min_commission', 0)
    for symbol in selected:
        position = positions.get(symbol, {})
        price = _price(symbol, data, position)
        if price <= 0:
            return False
        current_value = position.get('shares', 0) * price
        target_value = total_value * weights.get(symbol, 0)
        tolerance = max(min_commission, price * 100)
        if abs(target_value - current_value) >= tolerance:
            return False
    return True


def _estimated_sell_proceeds(
    amount: float,
    sell_commission_rate: float,
    min_commission: float,
) -> float:
    commission = max(amount * sell_commission_rate, min_commission)
    return max(amount - commission, 0)


def _target_exposure(
    data: dict,
    symbols: list[str],
    config: TrendCandidateConfig,
) -> float:
    if config.exposure_mode == 'static':
        return config.target_exposure
    if config.exposure_mode != 'trend_strength':
        raise ValueError(f'unknown exposure_mode: {config.exposure_mode}')

    market_strength = _market_trend_strength(
        data.get(config.market_proxy) or {},
        config.market_trend_window,
    )
    breadth = _trend_breadth(data, symbols, config.breadth_window)
    if market_strength is None or breadth is None:
        return config.target_exposure * 0.50

    if (
        market_strength >= 0.06
        and breadth >= min(config.breadth_threshold + 0.25, 1.0)
    ):
        return config.target_exposure
    if (
        market_strength >= 0.02
        and breadth >= min(config.breadth_threshold + 0.10, 1.0)
    ):
        return config.target_exposure * 0.75
    return config.target_exposure * 0.50


def _weights(
    items: list[dict],
    config: TrendCandidateConfig,
    target_exposure: float | None = None,
) -> dict[str, float]:
    if not items:
        return {}
    exposure = config.target_exposure if target_exposure is None else target_exposure
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
        symbol: min(weight * exposure, config.max_weight_per_etf)
        for symbol, weight in raw.items()
    }


def _stabilized_selection(
    ranked: list[dict],
    actual_positions: list[str],
    max_holdings: int,
    min_switch_score_gap: float,
) -> list[str]:
    default = [item['symbol'] for item in ranked[:max_holdings]]
    if min_switch_score_gap <= 0 or not actual_positions:
        return default
    ranked_by_symbol = {item['symbol']: item for item in ranked}
    current = [
        symbol
        for symbol in actual_positions
        if symbol in ranked_by_symbol
    ][:max_holdings]
    if len(current) != len(default):
        return default
    default_score = _average_score(
        ranked_by_symbol[symbol]
        for symbol in default
    )
    current_score = _average_score(
        ranked_by_symbol[symbol]
        for symbol in current
    )
    if default_score - current_score < min_switch_score_gap:
        return current
    return default


def _average_score(items) -> float:
    values = [item['score'] for item in items]
    return sum(values) / len(values) if values else float('-inf')


def _trend_breadth(
    data: dict,
    symbols: list[str],
    window: int,
) -> float | None:
    valid_count = 0
    above_count = 0
    for symbol in symbols:
        prices = _prices(data.get(symbol) or {})
        if len(prices) < window:
            continue
        valid_count += 1
        if prices[-1] >= sum(prices[-window:]) / window:
            above_count += 1
    if valid_count == 0:
        return None
    return above_count / valid_count


def _market_trend_strength(bar: dict, window: int) -> float | None:
    prices = _prices(bar)
    if len(prices) < window:
        return None
    latest = prices[-1]
    trend_ma = sum(prices[-window:]) / window
    if latest <= 0 or trend_ma <= 0:
        return None
    return latest / trend_ma - 1.0


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
