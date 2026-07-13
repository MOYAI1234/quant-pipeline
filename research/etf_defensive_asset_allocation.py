import json
import math
from collections import Counter
from dataclasses import dataclass

from strategy.base import BaseStrategy

from research.etf_dual_momentum import (
    calculate_factor,
    load_rotation_csv as load_rotation_csv,
    month_end_dates,
)


@dataclass(frozen=True)
class DefensiveAssetAllocationConfig:
    lookback_days: int = 252
    min_history_days: int = 253
    min_amount: float | None = None
    risk_holdings: int = 2
    defensive_holdings: int = 1
    canary_threshold: float = 1.0
    breadth_threshold: float = 0.5
    cash_return: float = 0.0

    def __post_init__(self):
        if self.lookback_days <= 0:
            raise ValueError('lookback_days 必须大于 0')
        if self.min_history_days <= 0:
            raise ValueError('min_history_days 必须大于 0')
        if self.risk_holdings <= 0:
            raise ValueError('risk_holdings 必须大于 0')
        if self.defensive_holdings <= 0:
            raise ValueError('defensive_holdings 必须大于 0')
        if self.min_amount is not None and self.min_amount < 0:
            raise ValueError('min_amount 不能小于 0')
        _validate_ratio(self.canary_threshold, 'canary_threshold')
        _validate_ratio(self.breadth_threshold, 'breadth_threshold')

    @property
    def required_prices(self) -> int:
        return max(self.lookback_days + 1, self.min_history_days)


class ETFDefensiveAssetAllocationBacktestStrategy(BaseStrategy):
    """ETF-DAA-003 的本地回测适配层。"""

    def __init__(
        self,
        risk_assets: list[str],
        defensive_assets: list[str],
        canary_assets: list[str],
        factor_config: DefensiveAssetAllocationConfig | None = None,
        *,
        rebalance_dates: set[str] | None = None,
        execution_buffer_rate: float = 0.0,
        name: str = 'ETF-DAA-003 本地回测',
    ):
        risk_assets = _normalize_symbols(risk_assets, 'risk_assets')
        defensive_assets = _normalize_symbols(defensive_assets, 'defensive_assets')
        canary_assets = _normalize_symbols(canary_assets, 'canary_assets')
        _validate_disjoint(
            risk_assets,
            defensive_assets,
            'risk_assets',
            'defensive_assets',
        )
        _validate_execution_buffer(execution_buffer_rate)

        etf_pool = _unique_preserve_order(risk_assets + defensive_assets + canary_assets)
        super().__init__({
            'name': name,
            'symbol': etf_pool[0],
            'etf_pool': etf_pool,
        })
        self.risk_assets = risk_assets
        self.defensive_assets = defensive_assets
        self.canary_assets = canary_assets
        self.etf_pool = etf_pool
        self.factor_config = factor_config or DefensiveAssetAllocationConfig()
        self.rebalance_dates = set(rebalance_dates or [])
        self.execution_buffer_rate = float(execution_buffer_rate)
        self.selected_etfs = []
        self.evaluation_count = 0
        self.selected_history = []
        self.regime_counts = Counter()
        self.rejection_reasons = Counter()
        self.last_evaluation = None

    def generate_signal(self, data: dict, portfolio: dict = None) -> list:
        date = data.get('_date', data.get('date', data.get('timestamp', '')))
        if self.rebalance_dates and date not in self.rebalance_dates:
            return []

        snapshot = _market_data_to_snapshot(data, self.etf_pool)
        evaluation = evaluate_snapshot(
            snapshot,
            self.factor_config,
            self.risk_assets,
            self.defensive_assets,
            self.canary_assets,
        )
        self.evaluation_count += 1
        self.last_evaluation = evaluation
        self.selected_etfs = list(evaluation['selected'])
        self.selected_history.append({
            'date': evaluation['date'],
            'regime': evaluation['regime'],
            'selected': list(evaluation['selected']),
            'canary_ratio': evaluation['canary_ratio'],
            'breadth_ratio': evaluation['breadth_ratio'],
        })
        self.regime_counts.update([evaluation['regime']])
        self.rejection_reasons.update(
            _base_rejection_reason(rejection['reason'])
            for rejection in evaluation['rejections']
        )
        return self._rebalance_signals(data, portfolio, self.selected_etfs)

    def calc_position_size(self, capital: float, price: float) -> int:
        if price <= 0 or not self.selected_etfs:
            return 0
        return int((capital / len(self.selected_etfs)) / price / 100) * 100

    def _rebalance_signals(
        self,
        data: dict,
        portfolio: dict | None,
        selected: list[str],
    ) -> list:
        signals = []
        positions = (portfolio or {}).get('positions', {})
        signal_time = data.get('_date') if isinstance(data, dict) else None
        costs = self._trading_costs(portfolio)

        for symbol, position in positions.items():
            if symbol in selected or position.get('shares', 0) <= 0:
                continue
            price = self._price_for(symbol, data, position)
            shares = int(position['shares'] // 100) * 100
            if price <= 0 or shares <= 0:
                continue
            signals.append({
                'action': 'sell',
                'symbol': symbol,
                'price': price,
                'shares': shares,
                'amount': shares * price,
                'reason': 'ETF-DAA-003 月频调仓卖出',
                'timestamp': signal_time,
            })

        if not selected:
            return signals

        target_value = (portfolio or {}).get('total_value', 0) / len(selected)
        available_capital = (portfolio or {}).get('capital', 0) + sum(
            self._net_sell_proceeds(signal['amount'], costs)
            for signal in signals
            if signal.get('action') == 'sell'
        )

        for symbol in selected:
            if symbol not in data:
                continue
            price = data[symbol].get('price', 0)
            if price <= 0:
                continue
            current_value = (
                positions.get(symbol, {}).get('market_value')
                or positions.get(symbol, {}).get('shares', 0) * price
            )
            budget = min(target_value - current_value, available_capital)
            shares = self._affordable_buy_shares(budget, price, costs)
            if shares <= 0:
                continue
            amount = shares * price
            signals.append({
                'action': 'buy',
                'symbol': symbol,
                'price': price,
                'shares': shares,
                'amount': amount,
                'reason': 'ETF-DAA-003 月频调仓买入',
                'timestamp': signal_time,
            })
            available_capital = max(
                available_capital - self._gross_buy_cost(amount, costs),
                0,
            )

        return signals

    def _price_for(self, symbol: str, data: dict, position: dict) -> float:
        if isinstance(data.get(symbol), dict):
            price = data[symbol].get('price', 0)
            if price > 0:
                return price
        return position.get('current_price', position.get('avg_price', 0))

    def _trading_costs(self, portfolio: dict | None) -> dict:
        costs = (portfolio or {}).get('trading_costs', {})
        return {
            'buy_commission_rate': costs.get('buy_commission_rate', 0),
            'sell_commission_rate': costs.get('sell_commission_rate', 0),
            'min_commission': costs.get('min_commission', 0),
        }

    def _net_sell_proceeds(self, amount: float, costs: dict) -> float:
        amount = amount * (1 - self.execution_buffer_rate)
        commission = max(
            amount * costs['sell_commission_rate'],
            costs['min_commission'],
        )
        return max(amount - commission, 0)

    def _gross_buy_cost(self, amount: float, costs: dict) -> float:
        amount = amount * (1 + self.execution_buffer_rate)
        return amount + max(
            amount * costs['buy_commission_rate'],
            costs['min_commission'],
        )

    def _affordable_buy_shares(
        self,
        budget: float,
        price: float,
        costs: dict,
    ) -> int:
        if budget <= 0 or price <= 0:
            return 0
        effective_price = price * (1 + self.execution_buffer_rate)
        max_notional = min(
            budget / (1 + costs['buy_commission_rate']),
            budget - costs['min_commission'],
        )
        if max_notional <= 0:
            return 0
        return int(max_notional / effective_price / 100) * 100


def evaluate_history(
    history: list,
    config: DefensiveAssetAllocationConfig,
    risk_assets: list[str],
    defensive_assets: list[str],
    canary_assets: list[str],
    *,
    rebalance_dates: set[str] | None = None,
    limit: int | None = None,
) -> list:
    dates = rebalance_dates or month_end_dates(history)
    results = []
    for snapshot in history:
        date = snapshot.get('date', snapshot.get('timestamp', ''))
        if date not in dates:
            continue
        results.append(
            evaluate_snapshot(
                snapshot,
                config,
                risk_assets,
                defensive_assets,
                canary_assets,
            )
        )
        if limit is not None and len(results) >= limit:
            break
    return results


def evaluate_snapshot(
    snapshot: dict,
    config: DefensiveAssetAllocationConfig,
    risk_assets: list[str],
    defensive_assets: list[str],
    canary_assets: list[str],
) -> dict:
    date = snapshot.get('date', snapshot.get('timestamp', ''))
    symbols = snapshot.get('symbols') or {}
    assets = _unique_preserve_order(risk_assets + defensive_assets + canary_assets)
    factors = {}
    rejections = []

    for symbol in _normalize_symbols(assets, 'assets'):
        if symbol not in symbols:
            rejections.append({'symbol': symbol, 'reason': 'missing_symbol'})
            continue
        factor, reason = calculate_factor(symbol, symbols[symbol], config)
        if factor is None:
            rejections.append({'symbol': symbol, 'reason': reason})
        else:
            factors[symbol] = factor

    canary_ranked = _rank_assets(factors, canary_assets)
    risk_ranked = _rank_assets(factors, risk_assets)
    defensive_ranked = _rank_assets(factors, defensive_assets)
    canary_ratio = _positive_ratio(canary_ranked, config.cash_return)
    breadth_ratio = _positive_ratio(risk_ranked, config.cash_return)
    risk_on = (
        canary_ranked
        and risk_ranked
        and canary_ratio >= config.canary_threshold
        and breadth_ratio >= config.breadth_threshold
    )

    if risk_on:
        regime = 'risk_on'
        selected = [
            item['symbol']
            for item in risk_ranked
            if item['momentum'] > config.cash_return
        ][:config.risk_holdings]
    else:
        defensive_leaders = [
            item['symbol']
            for item in defensive_ranked
            if item['momentum'] > config.cash_return
        ][:config.defensive_holdings]
        if defensive_leaders:
            regime = 'risk_off'
            selected = defensive_leaders
        else:
            regime = 'cash'
            selected = []

    return {
        'date': date,
        'regime': regime,
        'selected': selected,
        'canary_ratio': canary_ratio,
        'breadth_ratio': breadth_ratio,
        'canary_ranked': canary_ranked,
        'risk_ranked': risk_ranked,
        'defensive_ranked': defensive_ranked,
        'rejections': rejections,
    }


def backtest_diagnostics(
    strategy: ETFDefensiveAssetAllocationBacktestStrategy,
) -> dict:
    selected_count = sum(
        1 for item in strategy.selected_history
        if item['selected']
    )
    return {
        'evaluation_count': strategy.evaluation_count,
        'selected_count': selected_count,
        'empty_count': strategy.evaluation_count - selected_count,
        'regime_counts': dict(strategy.regime_counts),
        'last_selected': (
            strategy.selected_history[-1]['selected']
            if strategy.selected_history else []
        ),
        'rejection_reasons': dict(strategy.rejection_reasons),
    }


def render_text(results: list) -> str:
    lines = []
    for result in results:
        lines.append(f"date={result['date']}")
        lines.append(f"regime={result['regime']}")
        lines.append(f"canary_ratio={result['canary_ratio']:.4f}")
        lines.append(f"breadth_ratio={result['breadth_ratio']:.4f}")
        selected = ','.join(result['selected']) if result['selected'] else '[]'
        lines.append(f"selected={selected}")
        _append_ranked(lines, 'canary_ranked', result['canary_ranked'])
        _append_ranked(lines, 'risk_ranked', result['risk_ranked'])
        _append_ranked(lines, 'defensive_ranked', result['defensive_ranked'])
        if result['rejections']:
            lines.append('rejections:')
            for rejection in result['rejections']:
                lines.append(
                    f"- {rejection['symbol']}: {rejection['reason']}"
                )
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def render_json(results: list) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2) + '\n'


def _append_ranked(lines: list, label: str, ranked: list) -> None:
    if not ranked:
        return
    lines.append(f'{label}:')
    for item in ranked:
        lines.append(
            "- {symbol} momentum={momentum:.4f}".format(**item)
        )


def _rank_assets(factors: dict, assets: list[str]) -> list:
    return sorted(
        [
            factors[symbol]
            for symbol in assets
            if symbol in factors
        ],
        key=lambda item: item['momentum'],
        reverse=True,
    )


def _positive_ratio(ranked: list, cash_return: float) -> float:
    if not ranked:
        return 0.0
    positive_count = sum(
        1 for item in ranked
        if item['momentum'] > cash_return
    )
    return positive_count / len(ranked)


def _market_data_to_snapshot(data: dict, etf_pool: list[str]) -> dict:
    return {
        'date': data.get('_date', data.get('date', data.get('timestamp', ''))),
        'symbols': {
            symbol: _market_data_symbol_bar(data[symbol])
            for symbol in etf_pool
            if isinstance(data.get(symbol), dict)
        },
    }


def _market_data_symbol_bar(bar: dict) -> dict:
    snapshot_bar = {
        'close': bar.get('close', bar.get('price')),
        'prices': list(bar.get('prices', [])),
    }
    if 'volume' in bar:
        snapshot_bar['volume'] = bar['volume']
    if 'amount' in bar:
        snapshot_bar['amount'] = bar['amount']
    return snapshot_bar


def _normalize_symbols(symbols: list[str], label: str) -> list[str]:
    normalized = [symbol.strip() for symbol in symbols if symbol.strip()]
    if not normalized:
        raise ValueError(f'{label} 不能为空')
    duplicates = []
    seen = set()
    for symbol in normalized:
        if symbol in seen:
            duplicates.append(symbol)
        seen.add(symbol)
    if duplicates:
        raise ValueError(f'{label} 包含重复标的: {", ".join(sorted(set(duplicates)))}')
    return normalized


def _unique_preserve_order(symbols: list[str]) -> list[str]:
    unique = []
    seen = set()
    for symbol in symbols:
        if symbol not in seen:
            unique.append(symbol)
            seen.add(symbol)
    return unique


def _validate_disjoint(
    left: list[str],
    right: list[str],
    left_label: str,
    right_label: str,
) -> None:
    overlap = set(left) & set(right)
    if overlap:
        raise ValueError(
            f'{left_label} 和 {right_label} 不能重复: '
            + ', '.join(sorted(overlap))
        )


def _validate_ratio(value: float, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or value > 1
    ):
        raise ValueError(f'{label} 必须在 0 到 1 之间')


def _validate_execution_buffer(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or value >= 1
    ):
        raise ValueError('execution_buffer_rate 必须在 0 到 1 之间，且小于 1')


def _base_rejection_reason(reason: str) -> str:
    return reason.split()[0] if reason else 'unknown'
