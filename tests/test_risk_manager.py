from risk.risk_manager import RiskManager


def _risk_manager(config_overrides=None):
    config = {
        'max_position': 2,
        'max_single_weight': 0.5,
        'min_volume': 0,
        'min_size': 0,
        'max_premium': 1.0,
        'stop_loss': 0.15,
        'max_single_loss': 0.02,
        'trailing_stop': True,
        'trailing_pct': 0.05,
        'alert_threshold': -10,
    }
    config.update(config_overrides or {})
    return RiskManager(config)


def test_check_order_rejects_new_buy_when_position_count_is_full():
    manager = _risk_manager({'max_position': 1})
    portfolio = {
        'positions': {
            '510300': {'shares': 1000},
        },
        'total_value': 100000,
    }
    order = {
        'action': 'buy',
        'symbol': '510500',
        'amount': 10000,
    }

    result = manager.check_order(order, portfolio)

    assert result['passed'] is False
    assert result['checks'] == ['仓位已满: 1/1']


def test_check_order_allows_adding_to_existing_position_when_count_is_full():
    manager = _risk_manager({'max_position': 1})
    portfolio = {
        'positions': {
            '510300': {'shares': 1000},
        },
        'total_value': 100000,
    }
    order = {
        'action': 'buy',
        'symbol': '510300',
        'amount': 10000,
    }

    result = manager.check_order(order, portfolio)

    assert result['passed'] is True
    assert result['checks'] == []


def test_check_order_rejects_buy_when_single_order_weight_is_too_high():
    manager = _risk_manager({'max_single_weight': 0.25})
    portfolio = {
        'positions': {},
        'total_value': 100000,
    }
    order = {
        'action': 'buy',
        'symbol': '510300',
        'amount': 30000,
    }

    result = manager.check_order(order, portfolio)

    assert result['passed'] is False
    assert result['checks'] == ['单笔权重过大: 30.00% > 25.00%']


def test_check_order_rejects_sell_without_position():
    manager = _risk_manager()
    portfolio = {
        'positions': {},
        'total_value': 100000,
    }
    order = {
        'action': 'sell',
        'symbol': '510300',
        'amount': 10000,
    }

    result = manager.check_order(order, portfolio)

    assert result['passed'] is False
    assert result['checks'] == ['无持仓: 510300']


def test_check_portfolio_stop_loss_generates_fixed_stop_signal():
    manager = _risk_manager({'stop_loss': 0.1, 'max_single_loss': 0.2})
    portfolio = {
        'positions': {
            '510300': {
                'shares': 1000,
                'avg_price': 4.0,
                'current_price': 3.5,
            },
        },
    }

    signals = manager.check_portfolio_stop_loss(portfolio)

    assert signals == [{
        'action': 'sell',
        'symbol': '510300',
        'price': 3.5,
        'amount': 3500.0,
        'reason': '止损触发: 亏损12.50% >= 10.00%',
    }]


def test_check_portfolio_stop_loss_generates_single_loss_signal():
    manager = _risk_manager({'stop_loss': 0.15, 'max_single_loss': 0.02})
    portfolio = {
        'positions': {
            '510300': {
                'shares': 1000,
                'avg_price': 4.0,
                'current_price': 3.88,
            },
        },
    }

    signals = manager.check_portfolio_stop_loss(portfolio)

    assert signals == [{
        'action': 'sell',
        'symbol': '510300',
        'price': 3.88,
        'amount': 3880.0,
        'reason': '单笔止损触发: 亏损3.00% >= 2.00%',
    }]


def test_check_portfolio_stop_loss_tracks_high_price_before_trailing_stop():
    manager = _risk_manager({
        'stop_loss': 0.3,
        'max_single_loss': 0.3,
        'trailing_stop': True,
        'trailing_pct': 0.05,
    })
    portfolio = {
        'positions': {
            '510300': {
                'shares': 1000,
                'avg_price': 4.0,
                'current_price': 4.3,
            },
        },
    }
    assert manager.check_portfolio_stop_loss(portfolio) == []
    portfolio['positions']['510300']['current_price'] = 4.08

    signals = manager.check_portfolio_stop_loss(portfolio)

    assert signals == [{
        'action': 'sell',
        'symbol': '510300',
        'price': 4.08,
        'amount': 4080.0,
        'reason': '跟踪止损触发: 回撤5.12% >= 5.00%',
    }]


def test_check_portfolio_stop_loss_skips_invalid_position_prices():
    manager = _risk_manager()
    portfolio = {
        'positions': {
            '510300': {
                'shares': 1000,
                'avg_price': 0,
                'current_price': 3.5,
            },
        },
    }

    assert manager.check_portfolio_stop_loss(portfolio) == []


def test_check_portfolio_risk_reports_total_loss_alert():
    manager = _risk_manager({'alert_threshold': -8})

    result = manager.check_portfolio_risk({'pnl_percent': -8.5})

    assert result == {
        'safe': False,
        'alerts': ['总亏损告警: -8.50%'],
    }
