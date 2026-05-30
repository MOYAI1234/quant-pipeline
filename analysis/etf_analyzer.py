from adapters.mx_data_adapter import MXDataAdapter


class ETFAnalyzer:

    def __init__(self, config):
        self.mx_data = MXDataAdapter(config.get('mx_data', {}))

    def analyze_etf(self, symbol: str) -> dict:
        realtime = self.mx_data.get_etf_realtime(symbol)
        nav = self.mx_data.get_etf_nav(symbol)
        premium = nav.get('premium', 0)

        return {
            'symbol': symbol,
            'price': realtime.get('price', 0),
            'nav': nav.get('nav', 0),
            'premium': premium,
            'premium_level': self._get_premium_level(premium),
            'recommendation': self._get_recommendation(premium)
        }

    def compare_etfs(self, symbols: list) -> list:
        results = []
        for symbol in symbols:
            results.append(self.analyze_etf(symbol))
        return sorted(results, key=lambda x: abs(x.get('premium', 0)))

    def _get_premium_level(self, premium: float) -> str:
        if premium > 2:
            return "高溢价"
        elif premium < -2:
            return "高折价"
        else:
            return "正常"

    def _get_recommendation(self, premium: float) -> str:
        if premium > 2:
            return "溢价过高，建议谨慎买入"
        elif premium < -2:
            return "折价明显，可考虑买入"
        else:
            return "价格正常"
