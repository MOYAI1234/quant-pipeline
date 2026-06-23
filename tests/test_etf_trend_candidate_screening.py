import csv
import json

from scripts.screen_etf_trend_candidates import (
    ETFTrendCandidateStrategy,
    TrendCandidateConfig,
    _candidate_configs,
    _screening_summary,
    _stabilized_selection,
    _target_weight_signals,
    _target_exposure,
    _write_decision_log,
    _summary,
    _write_candidate_results,
    _write_screening_summary,
)


def _config(use_market_filter=False):
    return TrendCandidateConfig(
        name='TEST-GUARD',
        family='test',
        market_proxy='510300',
        rebalance_interval=20,
        max_holdings=1,
        max_weight_per_etf=1.0,
        fast_window=1,
        slow_window=2,
        trend_window=2,
        market_trend_window=2,
        breadth_window=2,
        breadth_threshold=0.5,
        vol_window=2,
        drawdown_window=2,
        max_recent_drawdown=0.5,
        require_own_trend=False,
        use_market_filter=use_market_filter,
        use_breadth_filter=False,
        weight_mode='equal',
        target_exposure=1.0,
        exposure_mode='static',
        min_switch_score_gap=0.0,
    )


def _bar(price, prices=None):
    return {
        'price': price,
        'prices': list(prices or [10.0, 11.0, price]),
        'volume': 1000000,
    }


def test_weak_market_exit_retries_until_actual_position_is_gone():
    strategy = ETFTrendCandidateStrategy(['510300', '510500'], _config(True))
    data = {
        '510300': _bar(10.0, [12.0, 11.0, 10.0]),
        '510500': _bar(9.0, [10.0, 9.5, 9.0]),
    }

    first_signals = strategy.generate_signal(data, {
        'capital': 0,
        'total_value': 10000,
        'positions': {
            '510300': {'shares': 1000, 'current_price': 10.0},
        },
    })
    retry_signals = strategy.generate_signal(data, {
        'capital': 0,
        'total_value': 5000,
        'positions': {
            '510300': {'shares': 500, 'current_price': 10.0},
        },
    })
    settled_signals = strategy.generate_signal(data, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })

    assert [signal['action'] for signal in first_signals] == ['sell']
    assert first_signals[0]['shares'] == 1000
    assert [signal['action'] for signal in retry_signals] == ['sell']
    assert retry_signals[0]['shares'] == 500
    assert settled_signals == []
    assert strategy.pending_targets is None
    assert strategy.decision_history[-1]['decision'] == 'pending_settled'
    assert strategy.decision_history[-1]['selected'] == []


def test_target_rotation_retries_same_winner_until_target_weight_is_reached():
    strategy = ETFTrendCandidateStrategy(['510300', '510500'], _config())
    data = {
        '510300': _bar(10.0, [8.0, 9.0, 10.0]),
        '510500': _bar(8.0, [8.0, 8.1, 8.0]),
    }

    first_signals = strategy.generate_signal(data, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })
    retry_signals = strategy.generate_signal(data, {
        'capital': 9000,
        'total_value': 10000,
        'positions': {
            '510300': {'shares': 100, 'current_price': 10.0},
        },
    })
    settled_signals = strategy.generate_signal(data, {
        'capital': 0,
        'total_value': 10000,
        'positions': {
            '510300': {'shares': 1000, 'current_price': 10.0},
        },
    })

    assert [signal['action'] for signal in first_signals] == ['buy']
    assert first_signals[0]['shares'] == 1000
    assert [signal['action'] for signal in retry_signals] == ['buy']
    assert retry_signals[0]['shares'] == 900
    assert settled_signals == []
    assert strategy.current_targets == ['510300']
    assert strategy.pending_targets is None


def test_pending_retry_recomputes_adaptive_exposure_before_buying_more():
    config = TrendCandidateConfig(
        **{
            **_config(use_market_filter=True).__dict__,
            'target_exposure': 1.0,
            'exposure_mode': 'trend_strength',
            'use_breadth_filter': True,
            'breadth_threshold': 0.5,
            'breadth_window': 2,
            'market_trend_window': 2,
        }
    )
    strategy = ETFTrendCandidateStrategy(['510300'], config)

    strong_data = {
        '510300': _bar(10.0, [8.0, 8.0, 10.0]),
    }
    marginal_data = {
        '510300': _bar(10.1, [10.0, 10.0, 10.1]),
    }

    first_signals = strategy.generate_signal(strong_data, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })
    retry_signals = strategy.generate_signal(marginal_data, {
        'capital': 9000,
        'total_value': 10000,
        'positions': {
            '510300': {'shares': 100, 'current_price': 10.1},
        },
    })

    assert first_signals[0]['shares'] == 1000
    assert retry_signals[0]['action'] == 'buy'
    assert retry_signals[0]['shares'] == 300
    assert strategy.pending_weights == {'510300': 0.5}
    assert strategy.decision_history[-1]['decision'] == 'pending_retry'
    assert strategy.decision_history[-1]['target_exposure'] == 0.5


def test_pending_retry_recomputes_adaptive_exposure_when_market_improves():
    config = TrendCandidateConfig(
        **{
            **_config(use_market_filter=True).__dict__,
            'target_exposure': 1.0,
            'exposure_mode': 'trend_strength',
            'use_breadth_filter': True,
            'breadth_threshold': 0.5,
            'breadth_window': 2,
            'market_trend_window': 2,
        }
    )
    strategy = ETFTrendCandidateStrategy(['510300'], config)

    marginal_data = {
        '510300': _bar(10.1, [10.0, 10.0, 10.1]),
    }
    strong_data = {
        '510300': _bar(10.0, [8.0, 8.0, 10.0]),
    }

    first_signals = strategy.generate_signal(marginal_data, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })
    retry_signals = strategy.generate_signal(strong_data, {
        'capital': 9000,
        'total_value': 10000,
        'positions': {
            '510300': {'shares': 100, 'current_price': 10.0},
        },
    })

    assert first_signals[0]['shares'] == 400
    assert retry_signals[0]['action'] == 'buy'
    assert retry_signals[0]['shares'] == 900
    assert strategy.pending_weights == {'510300': 1.0}
    assert strategy.decision_history[-1]['decision'] == 'pending_retry'
    assert strategy.decision_history[-1]['target_exposure'] == 1.0


def test_static_pending_retry_preserves_capped_weights():
    strategy = ETFTrendCandidateStrategy(['510300', '510500'], _config())
    strategy.pending_targets = ['510300', '510500']
    strategy.pending_weights = {
        '510300': 0.50,
        '510500': 0.09,
    }

    signals = strategy.generate_signal({
        '510300': _bar(10.0),
        '510500': _bar(10.0),
    }, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {
            '510300': {'shares': 100, 'current_price': 10.0},
        },
    })

    assert strategy.pending_weights == {
        '510300': 0.50,
        '510500': 0.09,
    }
    assert [signal['symbol'] for signal in signals] == ['510300']
    assert signals[0]['shares'] == 400


def test_breadth_filter_blocks_new_buy_when_pool_trend_is_weak():
    config = TrendCandidateConfig(
        name='TEST-BREADTH',
        family='test',
        market_proxy='510300',
        rebalance_interval=1,
        max_holdings=1,
        max_weight_per_etf=1.0,
        fast_window=1,
        slow_window=2,
        trend_window=2,
        market_trend_window=2,
        breadth_window=2,
        breadth_threshold=0.75,
        vol_window=2,
        drawdown_window=2,
        max_recent_drawdown=0.5,
        require_own_trend=False,
        use_market_filter=False,
        use_breadth_filter=True,
        weight_mode='equal',
        target_exposure=1.0,
        exposure_mode='static',
        min_switch_score_gap=0.0,
    )
    strategy = ETFTrendCandidateStrategy(['510300', '510500'], config)

    signals = strategy.generate_signal({
        '510300': _bar(10.0, [9.0, 11.0, 10.0]),
        '510500': _bar(9.0, [9.0, 10.0, 9.0]),
    }, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })

    assert signals == []
    assert strategy.rejection_reasons['breadth_weak'] == 1


def test_stabilized_selection_keeps_current_position_when_edge_is_small():
    ranked = [
        {'symbol': '510300', 'score': 0.1100},
        {'symbol': '510500', 'score': 0.1005},
    ]

    assert _stabilized_selection(ranked, ['510500'], 1, 0.01) == ['510500']
    assert _stabilized_selection(ranked, ['510500'], 1, 0.005) == ['510300']


def test_candidate_configs_include_daily_core_guard_profiles():
    configs = _candidate_configs('510300')
    daily_only = _candidate_configs('510300', 'daily_core_guard')

    daily_configs = [
        config for config in configs
        if config.family == 'daily_core_guard'
    ]

    assert daily_configs
    assert any(config.rebalance_interval == 1 for config in daily_configs)
    assert all(config.use_breadth_filter for config in configs)
    assert all(config.min_switch_score_gap > 0 for config in configs)
    assert daily_only
    assert {config.family for config in daily_only} == {'daily_core_guard'}


def test_candidate_configs_include_adaptive_exposure_profiles():
    configs = _candidate_configs('510300', 'adaptive_exposure_guard')

    assert configs
    assert {config.family for config in configs} == {'adaptive_exposure_guard'}
    assert {config.exposure_mode for config in configs} == {'trend_strength'}
    assert all(config.max_holdings == 1 for config in configs)


def test_candidate_configs_include_recovery_trend_profiles():
    configs = _candidate_configs('510300', 'recovery_trend_guard')

    assert configs
    assert {config.family for config in configs} == {'recovery_trend_guard'}
    assert {config.factor_mode for config in configs} == {'recovery'}
    assert all(config.recovery_threshold > 0 for config in configs)
    assert all(config.max_holdings == 1 for config in configs)


def test_recovery_trend_guard_requires_mid_range_recovery():
    config = TrendCandidateConfig(
        **{
            **_config().__dict__,
            'rebalance_interval': 1,
            'fast_window': 1,
            'slow_window': 3,
            'trend_window': 2,
            'vol_window': 3,
            'drawdown_window': 4,
            'factor_mode': 'recovery',
            'recovery_threshold': 0.60,
            'max_recent_drawdown': 0.50,
        }
    )
    strategy = ETFTrendCandidateStrategy(['510300'], config)

    weak_recovery_signals = strategy.generate_signal({
        '510300': _bar(9.0, [8.0, 12.0, 8.0, 9.0]),
    }, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })
    strong_recovery_signals = strategy.generate_signal({
        '510300': _bar(11.0, [8.0, 12.0, 8.0, 11.0]),
    }, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })

    assert weak_recovery_signals == []
    assert strategy.rejection_reasons['insufficient_recovery'] == 1
    assert [signal['action'] for signal in strong_recovery_signals] == ['buy']


def test_trend_strength_exposure_steps_down_on_marginal_market():
    config = _config(use_market_filter=True)
    config = TrendCandidateConfig(
        **{
            **config.__dict__,
            'target_exposure': 1.0,
            'exposure_mode': 'trend_strength',
            'use_breadth_filter': True,
            'breadth_threshold': 0.5,
            'breadth_window': 2,
            'market_trend_window': 2,
        }
    )

    strong_data = {
        '510300': _bar(12.0, [10.0, 10.0, 12.0]),
        '510500': _bar(12.0, [10.0, 10.0, 12.0]),
    }
    normal_data = {
        '510300': _bar(10.5, [10.0, 10.0, 10.5]),
        '510500': _bar(10.5, [10.0, 10.0, 10.5]),
    }
    marginal_data = {
        '510300': _bar(10.1, [10.0, 10.0, 10.1]),
        '510500': _bar(10.1, [10.0, 10.0, 10.1]),
    }

    assert _target_exposure(strong_data, ['510300', '510500'], config) == 1.0
    assert _target_exposure(normal_data, ['510300', '510500'], config) == 0.75
    assert _target_exposure(marginal_data, ['510300', '510500'], config) == 0.5


def test_target_weight_signals_reuses_selected_leg_reduction_proceeds():
    signals = _target_weight_signals(
        {
            '_date': '2026-01-20',
            '510300': _bar(10.0),
            '510500': _bar(10.0),
        },
        {
            'capital': 0,
            'total_value': 10000,
            'positions': {
                '510300': {'shares': 800, 'current_price': 10.0},
                '510500': {'shares': 200, 'current_price': 10.0},
            },
            'trading_costs': {
                'buy_commission_rate': 0,
                'sell_commission_rate': 0,
                'min_commission': 0,
            },
        },
        ['510300', '510500'],
        {'510300': 0.5, '510500': 0.5},
        '测试再平衡',
    )

    assert [signal['action'] for signal in signals] == ['sell', 'buy']
    assert signals[0]['symbol'] == '510300'
    assert signals[0]['shares'] == 300
    assert signals[1]['symbol'] == '510500'
    assert signals[1]['shares'] == 300


def test_decision_history_records_rebalance_context():
    config = TrendCandidateConfig(
        **{
            **_config(use_market_filter=True).__dict__,
            'target_exposure': 1.0,
            'exposure_mode': 'trend_strength',
            'use_breadth_filter': True,
            'breadth_threshold': 0.5,
            'breadth_window': 2,
            'market_trend_window': 2,
        }
    )
    strategy = ETFTrendCandidateStrategy(['510300'], config)

    signals = strategy.generate_signal({
        '_date': '2026-01-05',
        '510300': _bar(10.0, [8.0, 8.0, 10.0]),
    }, {
        'capital': 10000,
        'total_value': 10000,
        'positions': {},
    })

    assert signals
    decision = strategy.decision_history[-1]
    assert decision['date'] == '2026-01-05'
    assert decision['decision'] == 'rebalance'
    assert decision['selected'] == ['510300']
    assert decision['target_exposure'] == 1.0
    assert decision['weights'] == {'510300': 1.0}
    assert decision['signals'][0]['action'] == 'buy'
    assert decision['top_candidates'][0]['symbol'] == '510300'


def test_summary_includes_automatic_gate_decision():
    strategy = ETFTrendCandidateStrategy(['510300'], _config())
    result = {
        'start_date': '2020-01-01',
        'end_date': '2025-01-01',
        'total_return': 0.5,
        'max_drawdown': 0.1,
        'trade_count': 5,
        'turnover_ratio': 5.0,
        'commission_ratio': 0.005,
        'final_value': 150000,
        'trades': [
            {'timestamp': f'202{i}-01-02T09:30:00'}
            for i in range(5)
        ],
        'portfolio_curve': [
            {'total_value': 100000, 'positions_market_value': 80000},
        ],
    }

    summary = _summary(result, strategy)

    assert summary['gate_status'] == 'PASS'
    assert summary['family'] == 'test'
    assert summary['max_daily_trades'] == 1
    assert summary['gate_reasons']
    assert summary['decision_history'] == []


def test_screening_summary_aggregates_statuses_and_failure_reasons():
    results = [
        _candidate_result(
            'alpha',
            'daily_core_guard',
            'REJECT',
            0.01,
            0.18,
            ['annual_return 1.00% < 6.00%', 'max_drawdown 18.00% > 15.00%'],
            {'breadth_weak': 7},
        ),
        _candidate_result(
            'beta',
            'daily_core_guard',
            'WATCHLIST',
            0.055,
            0.12,
            ['annual_return 5.50% < 6.00%'],
            {'market_trend_weak': 3},
        ),
        _candidate_result(
            'gamma',
            'swing_trend_guard',
            'PASS',
            0.08,
            0.09,
            [],
            {},
        ),
    ]

    summary = _screening_summary(results, [results[2]])

    assert summary['evaluated_candidates'] == 3
    assert summary['visible_candidates'] == 1
    assert summary['status_counts'] == {
        'REJECT': 1,
        'WATCHLIST': 1,
        'PASS': 1,
    }
    assert summary['family_status_counts']['daily_core_guard'] == {
        'REJECT': 1,
        'WATCHLIST': 1,
    }
    assert summary['gate_reason_counts']['annual_return 5.50% < 6.00%'] == 1
    assert summary['rejection_reason_counts']['breadth_weak'] == 7
    assert summary['best_by_drawdown']['name'] == 'gamma'
    assert summary['best_by_annual']['name'] == 'gamma'


def test_candidate_results_can_be_written_as_json_and_csv(tmp_path):
    results = [
        _candidate_result(
            'alpha',
            'daily_core_guard',
            'REJECT',
            0.01,
            0.18,
            ['annual_return 1.00% < 6.00%'],
            {'breadth_weak': 7},
        )
    ]
    json_path = tmp_path / 'candidates.json'
    csv_path = tmp_path / 'candidates.csv'

    _write_candidate_results(str(json_path), results)
    _write_candidate_results(str(csv_path), results)

    assert json.loads(json_path.read_text(encoding='utf-8'))[0]['name'] == 'alpha'
    with csv_path.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert rows[0]['name'] == 'alpha'
    assert rows[0]['gate_reasons'] == 'annual_return 1.00% < 6.00%'
    assert json.loads(rows[0]['rejection_reasons']) == {'breadth_weak': 7}


def test_decision_log_can_be_written_as_json_and_csv(tmp_path):
    results = [
        {
            **_candidate_result(
                'alpha',
                'adaptive_exposure_guard',
                'WATCHLIST',
                0.04,
                0.18,
                ['max_drawdown 18.00% > 15.00%'],
                {},
            ),
            'decision_history': [
                {
                    'date': '2026-01-05',
                    'decision': 'rebalance',
                    'selected': ['510300'],
                    'target_exposure': 0.8,
                    'market_strength': 0.03,
                    'breadth': 0.75,
                    'weights': {'510300': 0.8},
                    'actual_positions': [],
                    'signals': [{'action': 'buy', 'symbol': '510300'}],
                    'top_candidates': [{'symbol': '510300', 'score': 0.12}],
                },
            ],
        }
    ]
    json_path = tmp_path / 'decisions.json'
    csv_path = tmp_path / 'decisions.csv'

    _write_decision_log(str(json_path), results)
    _write_decision_log(str(csv_path), results)

    json_rows = json.loads(json_path.read_text(encoding='utf-8'))
    assert json_rows[0]['candidate'] == 'alpha'
    assert json_rows[0]['selected'] == ['510300']
    with csv_path.open(newline='', encoding='utf-8') as file:
        csv_rows = list(csv.DictReader(file))
    assert csv_rows[0]['candidate'] == 'alpha'
    assert json.loads(csv_rows[0]['weights']) == {'510300': 0.8}


def test_screening_summary_can_be_written_as_json_and_csv(tmp_path):
    summary = _screening_summary([
        _candidate_result(
            'alpha',
            'daily_core_guard',
            'REJECT',
            0.01,
            0.18,
            ['annual_return 1.00% < 6.00%'],
            {'breadth_weak': 7},
        )
    ])
    json_path = tmp_path / 'summary.json'
    csv_path = tmp_path / 'summary.csv'

    _write_screening_summary(str(json_path), summary)
    _write_screening_summary(str(csv_path), summary)

    assert json.loads(json_path.read_text(encoding='utf-8'))[
        'evaluated_candidates'
    ] == 1
    with csv_path.open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    assert {
        'section': 'total',
        'family': 'all',
        'key': 'evaluated_candidates',
        'value': '1',
    } in rows
    assert any(
        row['section'] == 'rejection_reason_counts'
        and row['key'] == 'breadth_weak'
        and row['value'] == '7'
        for row in rows
    )


def _candidate_result(
    name,
    family,
    gate_status,
    annual_return,
    max_drawdown,
    gate_reasons,
    rejection_reasons,
):
    return {
        'name': name,
        'family': family,
        'annual_return': annual_return,
        'total_return': annual_return,
        'max_drawdown': max_drawdown,
        'trade_count': 5,
        'turnover_ratio': 1.2,
        'commission_ratio': 0.001,
        'annual_turnover': 0.3,
        'annual_commission_ratio': 0.0003,
        'max_daily_trades': 1,
        'cash_day_ratio': 0.2,
        'gate_status': gate_status,
        'gate_reasons': list(gate_reasons),
        'final_value': 101000,
        'regime_counts': {'risk_on': 1},
        'rejection_reasons': dict(rejection_reasons),
    }
