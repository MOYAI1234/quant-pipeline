from adapters.mx_data_adapter import MXDataAdapter
from adapters.mx_xuangu_adapter import MX_XuanguAdapter
from adapters.mx_search_adapter import MX_SearchAdapter
from .data_cache import DataCache, _SENTINEL


class DataManager:

    def __init__(self, config):
        self.mx_data = MXDataAdapter(config.get('mx_data', {}))
        self.mx_xuangu = MX_XuanguAdapter(config.get('mx_xuangu', {}))
        self.mx_search = MX_SearchAdapter(config.get('mx_search', {}))
        self.cache = DataCache(config.get('cache_ttl', 300))

    def connect(self):
        self.mx_data.connect()
        self.mx_xuangu.connect()
        self.mx_search.connect()

    def disconnect(self):
        self.mx_data.disconnect()
        self.mx_xuangu.disconnect()
        self.mx_search.disconnect()

    def get_etf_realtime(self, symbol: str) -> dict:
        cache_key = f"realtime_{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        data = self.mx_data.get_etf_realtime(symbol)
        self.cache.set(cache_key, data, ttl=10)
        return data

    def get_etf_history(self, symbol: str, start_date: str, end_date: str) -> list:
        cache_key = f"history_{symbol}_{start_date}_{end_date}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        data = self.mx_data.get_etf_history(symbol, start_date, end_date)
        self.cache.set(cache_key, data, ttl=3600)
        return data

    def get_etf_nav(self, symbol: str) -> dict:
        cache_key = f"nav_{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        data = self.mx_data.get_etf_nav(symbol)
        self.cache.set(cache_key, data, ttl=60)
        return data

    def get_etf_list(self, etf_type: str = None) -> list:
        cache_key = f"etf_list_{etf_type}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        data = self.mx_data.get_etf_list(etf_type)
        self.cache.set(cache_key, data, ttl=3600)
        return data

    def filter_etfs(self, conditions: dict) -> list:
        return self.mx_xuangu.filter_etfs(conditions)

    def search_news(self, keyword: str, days: int = 7) -> list:
        return self.mx_search.search_news(keyword, days)

    def health_check(self) -> dict:
        return {
            'mx_data': self.mx_data.health_check(),
            'mx_xuangu': self.mx_xuangu.health_check(),
            'mx_search': self.mx_search.health_check(),
        }
