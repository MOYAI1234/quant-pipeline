SYSTEM_CONFIG = {
    'data': {
        'max_realtime_age_seconds': None,
        'max_nav_age_seconds': None,
        'max_timestamp_future_skew_seconds': 60,
        'mx_data': {
            'mode': 'mock',
            'timeout': 10,
        },
        'mx_xuangu': {
            'mode': 'mock',
            'timeout': 10,
        },
        'mx_search': {
            'mode': 'mock',
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
        'alert_file_path': None,
    },
    'state': {
        'enabled': True,
        'path': 'data/state.json',
        'restore_on_start': True,
        'save_on_stop': True,
    }
}
