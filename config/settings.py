SYSTEM_CONFIG = {
    'data': {
        'mx_data': {
            'timeout': 10,
        },
        'mx_xuangu': {
            'timeout': 10,
        },
        'mx_search': {
            'timeout': 10,
        },
    },
    'account': {
        'initial_capital': 100000,
        'commission_rate': 0.0003,
    },
    'risk': {
        'max_position': 5,
        'stop_loss': 0.15,
        'max_single_loss': 0.02,
        'min_volume': 10000000,
        'min_size': 1000000000,
        'max_tracking_error': 0.005,
        'max_premium': 0.05,
    },
    'monitor': {
        'check_interval': 60,
        'alert_threshold': -10,
    }
}
