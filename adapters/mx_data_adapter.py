from .base_adapter import BaseAdapter


class MXDataAdapter(BaseAdapter):

    def __init__(self, config):
        super().__init__(config)

    def connect(self):
        self.connected = True

    def health_check(self) -> bool:
        return self.connected

    def get_etf_realtime(self, symbol: str) -> dict:
        return {
            'symbol': symbol,
            'price': 0.0,
            'open': 0.0,
            'high': 0.0,
            'low': 0.0,
            'volume': 0,
            'amount': 0.0,
            'timestamp': ''
        }

    def get_etf_history(self, symbol: str, start_date: str, end_date: str) -> list:
        return []

    def get_etf_nav(self, symbol: str) -> dict:
        return {
            'symbol': symbol,
            'nav': 0.0,
            'price': 0.0,
            'premium': 0.0
        }

    def get_etf_list(self, etf_type: str = None) -> list:
        return []
