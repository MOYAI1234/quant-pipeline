from scripts.screen_etf_trend_candidates import (
    ETFTrendCandidateStrategy,
    TrendCandidateConfig,
)


def _config(use_market_filter=False):
    return TrendCandidateConfig(
        name='TEST-GUARD',
        market_proxy='510300',
        rebalance_interval=20,
        max_holdings=1,
        max_weight_per_etf=1.0,
        fast_window=1,
        slow_window=2,
        trend_window=2,
        market_trend_window=2,
        vol_window=2,
        drawdown_window=2,
        max_recent_drawdown=0.5,
        require_own_trend=False,
        use_market_filter=use_market_filter,
        weight_mode='equal',
        target_exposure=1.0,
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
