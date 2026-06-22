import pytest

from research.candidate_gates import CandidateGateConfig, evaluate_candidate


def _metrics(**overrides):
    metrics = {
        'years': 5.0,
        'annual_return': 0.08,
        'max_drawdown': 0.10,
        'turnover_ratio': 10.0,
        'commission_ratio': 0.01,
        'trade_count': 6,
        'trades': [
            {'timestamp': f'202{i}-01-02T09:30:00'}
            for i in range(6)
        ],
        'portfolio_curve': [
            {'total_value': 100000, 'positions_market_value': 80000},
            {'total_value': 101000, 'positions_market_value': 0},
            {'total_value': 102000, 'positions_market_value': 90000},
        ],
    }
    metrics.update(overrides)
    return metrics


def test_candidate_passes_all_default_gates():
    decision = evaluate_candidate(_metrics())

    assert decision.status == 'PASS'
    assert decision.passed is True
    assert decision.annual_turnover == pytest.approx(2.0)
    assert decision.annual_commission_ratio == pytest.approx(0.002)
    assert decision.max_daily_trades == 1
    assert decision.cash_day_ratio == pytest.approx(1 / 3)


def test_performance_miss_is_watchlist_not_structural_rejection():
    decision = evaluate_candidate(_metrics(
        annual_return=0.059,
        max_drawdown=0.151,
    ))

    assert decision.status == 'WATCHLIST'
    assert len(decision.reasons) == 2
    assert '年化收益' in decision.reasons[0]
    assert '最大回撤' in decision.reasons[1]


def test_excess_daily_trades_is_rejected():
    trades = [
        {'timestamp': f'2026-01-02T0{hour}:30:00'}
        for hour in range(3)
    ] + [
        {'timestamp': f'202{i}-01-02T09:30:00'}
        for i in range(3)
    ]

    decision = evaluate_candidate(_metrics(trades=trades))

    assert decision.status == 'REJECT'
    assert decision.max_daily_trades == 3
    assert '超过上限 2' in decision.reasons[0]


def test_inactive_cash_only_result_is_rejected_even_with_zero_drawdown():
    decision = evaluate_candidate(_metrics(
        annual_return=0,
        max_drawdown=0,
        turnover_ratio=0,
        commission_ratio=0,
        trade_count=0,
        trades=[],
        portfolio_curve=[
            {'total_value': 100000, 'positions_market_value': 0},
            {'total_value': 100000, 'positions_market_value': 0},
        ],
    ))

    assert decision.status == 'REJECT'
    assert any('交易次数' in reason for reason in decision.reasons)
    assert any('纯现金日占比' in reason for reason in decision.reasons)


def test_gate_boundaries_are_inclusive():
    config = CandidateGateConfig(
        min_annual_return=0.08,
        max_drawdown=0.10,
        max_annual_turnover=2.0,
        max_annual_commission_ratio=0.002,
        max_trades_per_day=1,
        min_trade_count=6,
        max_cash_day_ratio=1 / 3,
    )

    assert evaluate_candidate(_metrics(), config).status == 'PASS'


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('years', 0),
        ('annual_return', float('nan')),
        ('trade_count', 1.5),
        ('trades', None),
        ('portfolio_curve', []),
    ],
)
def test_invalid_metrics_fail_closed(field, value):
    with pytest.raises(ValueError):
        evaluate_candidate(_metrics(**{field: value}))


def test_trade_count_must_match_serialized_trades():
    with pytest.raises(ValueError, match='trade_count'):
        evaluate_candidate(_metrics(trade_count=7))


def test_config_rejects_fractional_daily_trade_limit():
    with pytest.raises(ValueError, match='max_trades_per_day'):
        CandidateGateConfig(max_trades_per_day=1.5)
