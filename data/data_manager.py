from adapters.mx_data_adapter import MXDataAdapter
from adapters.mx_xuangu_adapter import MX_XuanguAdapter
from adapters.mx_search_adapter import MX_SearchAdapter
from .contracts import AdapterError, DataFetchError
from .data_cache import DataCache, _SENTINEL


class DataManager:
    QUOTE_FIELDS = (
        'symbol', 'price', 'open', 'high', 'low', 'pre_close',
        'volume', 'amount', 'timestamp'
    )
    NAV_FIELDS = ('symbol', 'nav', 'price', 'premium', 'timestamp')
    HISTORY_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')

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
        raw_data = self._call_adapter(
            'mx_data.realtime',
            self.mx_data.get_etf_realtime,
            symbol,
        )
        data = self._normalize_record(
            raw_data,
            self.QUOTE_FIELDS,
            source='mx_data.realtime',
        )
        self.cache.set(cache_key, data, ttl=10)
        return data

    def get_etf_history(self, symbol: str, start_date: str, end_date: str) -> list:
        cache_key = f"history_{symbol}_{start_date}_{end_date}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        raw_data = self._call_adapter(
            'mx_data.history',
            self.mx_data.get_etf_history,
            symbol,
            start_date,
            end_date,
        )
        data = self._normalize_records(
            raw_data,
            self.HISTORY_FIELDS,
            source='mx_data.history',
        )
        self.cache.set(cache_key, data, ttl=3600)
        return data

    def get_etf_nav(self, symbol: str) -> dict:
        cache_key = f"nav_{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        raw_data = self._call_adapter(
            'mx_data.nav',
            self.mx_data.get_etf_nav,
            symbol,
        )
        data = self._normalize_record(
            raw_data,
            self.NAV_FIELDS,
            source='mx_data.nav',
        )
        self.cache.set(cache_key, data, ttl=60)
        return data

    def get_etf_list(self, etf_type: str = None) -> list:
        cache_key = f"etf_list_{etf_type}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            return cached
        data = self._call_adapter(
            'mx_data.etf_list',
            self.mx_data.get_etf_list,
            etf_type,
        )
        self.cache.set(cache_key, data, ttl=3600)
        return data

    def filter_etfs(self, conditions: dict) -> list:
        return self._call_adapter(
            'mx_xuangu.filter_etfs',
            self.mx_xuangu.filter_etfs,
            conditions,
        )

    def search_news(self, keyword: str, days: int = 7) -> list:
        return self._call_adapter(
            'mx_search.search_news',
            self.mx_search.search_news,
            keyword,
            days,
        )

    def health_check(self) -> dict:
        return {
            'mx_data': self.mx_data.health_check(),
            'mx_xuangu': self.mx_xuangu.health_check(),
            'mx_search': self.mx_search.health_check(),
        }

    def is_mock_mode(self) -> bool:
        return all(
            status.get('mock', False)
            for status in self.health_check().values()
        )

    def _call_adapter(self, source: str, method, *args):
        try:
            return method(*args)
        except AdapterError:
            raise
        except Exception as exc:
            raise DataFetchError(
                f"{source} 调用失败: {exc}",
                error_code='ADAPTER_ERROR',
                source=source,
            ) from exc

    def _normalize_record(self, record: dict, required_fields: tuple, source: str) -> dict:
        if record is None:
            raise DataFetchError(
                f"{source} 返回值不能为 None",
                error_code='NULL_DATA',
                source=source,
            )

        if not isinstance(record, dict):
            raise DataFetchError(
                f"{source} 返回值必须是 dict，实际类型: {type(record).__name__}",
                error_code='INVALID_DATA_SHAPE',
                source=source,
            )

        if not record:
            raise DataFetchError(
                f"{source} 返回值不能为空字典",
                error_code='EMPTY_DATA',
                source=source,
            )

        missing = [field for field in required_fields if field not in record]
        if missing:
            raise DataFetchError(
                f"{source} 缺少字段: {', '.join(missing)}",
                error_code='MISSING_FIELDS',
                source=source,
            )

        return {field: record[field] for field in required_fields}

    def _normalize_records(self, records: list, required_fields: tuple, source: str) -> list:
        if not isinstance(records, list):
            raise DataFetchError(
                f"{source} 返回值必须是 list",
                error_code='INVALID_DATA_SHAPE',
                source=source,
            )

        return [
            self._normalize_record(record, required_fields, source)
            for record in records
        ]
