from .base_adapter import BaseAdapter


class MX_SearchAdapter(BaseAdapter):

    def __init__(self, config):
        super().__init__(config)

    def search_news(self, keyword: str, days: int = 7) -> list:
        self._ensure_available()
        return []

    def search_etf_news(self, symbol: str, days: int = 7) -> list:
        return self.search_news(f"{symbol} ETF", days)

    def search_policy_news(self, days: int = 7) -> list:
        return self.search_news("ETF 政策 监管", days)
