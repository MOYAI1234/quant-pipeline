from scripts.screen_etf_trend_candidates import (
    ETFTrendCandidateStrategy,
    TrendCandidateConfig,
    _candidate_configs,
    _stabilized_selection,
    _target_weight_signals,
    _summary,
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

    assert [signal['action'] for signal in first_signals] == ['sell']
    assert first_signals[0]['shares'] == 1000
    assert [signal['action'] for signal in retry_signals] == ['sell']
    assert retry_signals[0]['shares'] == 500


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
