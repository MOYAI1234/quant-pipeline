from adapters.mx_data_adapter import MXDataAdapter


class ETFRiskChecker:

    def __init__(self, config):
        self.mx_data = MXDataAdapter(config.get('mx_data', {}))
        self.mx_data.connect()
        self.min_volume = config.get('min_volume', 10000000)
        self.min_size = config.get('min_size', 1000000000)
        self.max_tracking_error = config.get('max_tracking_error', 0.005)
        self.max_premium = config.get('max_premium', 0.05)

    def check_etf_quality(self, symbol: str) -> dict:
        checks = []
        etf_info = self.mx_data.get_etf_realtime(symbol)
        nav_info = self.mx_data.get_etf_nav(symbol)

        if etf_info.get('volume', 0) < self.min_volume:
            checks.append(f"流动性不足: {etf_info.get('volume', 0)}")

        if etf_info.get('size', 0) < self.min_size:
            checks.append(f"规模太小: {etf_info.get('size', 0)}")

        premium = nav_info.get('premium', 0)
        if abs(premium) > self.max_premium:
            checks.append(f"溢价/折价过大: {premium:.2%}")

        return {
            'passed': len(checks) == 0,
            'checks': checks,
            'premium': premium
        }
