import math
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real

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
    TEXT_FIELDS = frozenset({'symbol', 'date', 'timestamp'})
    SIGNED_NUMBER_FIELDS = frozenset({'premium'})
    INTEGER_FIELDS = frozenset({'volume'})
    NON_NEGATIVE_NUMBER_FIELDS = frozenset({
        'price', 'open', 'high', 'low', 'pre_close', 'nav', 'close', 'amount',
    })
    VALIDATED_FIELDS = (
        TEXT_FIELDS
        | SIGNED_NUMBER_FIELDS
        | INTEGER_FIELDS
        | NON_NEGATIVE_NUMBER_FIELDS
    )
    CONTRACT_FIELDS = (
        frozenset(QUOTE_FIELDS)
        | frozenset(NAV_FIELDS)
        | frozenset(HISTORY_FIELDS)
    )
    UNCLASSIFIED_FIELDS = CONTRACT_FIELDS - VALIDATED_FIELDS
    if UNCLASSIFIED_FIELDS:
        raise RuntimeError(
            f"DataManager 缺少字段校验规则: {sorted(UNCLASSIFIED_FIELDS)}"
        )

    def __init__(self, config):
        self.mx_data = MXDataAdapter(config.get('mx_data', {}))
        self.mx_xuangu = MX_XuanguAdapter(config.get('mx_xuangu', {}))
        self.mx_search = MX_SearchAdapter(config.get('mx_search', {}))
        self.cache = DataCache(config.get('cache_ttl', 300))
        self.history_cache_ttl_seconds = config.get(
            'history_cache_ttl_seconds',
            3600,
        )
        self.history_cache_hits = 0
        self.history_cache_misses = 0
        self.last_history_cache_key = None
        self.last_history_cache_hit = None
        self.max_realtime_age_seconds = config.get('max_realtime_age_seconds')
        self.max_nav_age_seconds = config.get('max_nav_age_seconds')
        self.max_timestamp_future_skew_seconds = config.get(
            'max_timestamp_future_skew_seconds',
            60,
        )
        self.timestamp_timezone = self._parse_timezone_offset(
            config.get('timestamp_timezone_offset', '+08:00')
        )

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
            self._validate_timestamp_freshness(
                cached['timestamp'],
                source='mx_data.realtime',
                max_age_seconds=self.max_realtime_age_seconds,
            )
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
        cache_ttl = self._freshness_limited_ttl(
            default_ttl=10,
            timestamp=data['timestamp'],
            source='mx_data.realtime',
            max_age_seconds=self.max_realtime_age_seconds,
        )
        self.cache.set(cache_key, data, ttl=cache_ttl)
        return data

    def get_etf_history(self, symbol: str, start_date: str, end_date: str) -> list:
        cache_key = f"history_{symbol}_{start_date}_{end_date}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            self._record_history_cache_access(cache_key, hit=True)
            return cached
        self._record_history_cache_access(cache_key, hit=False)
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
        self.cache.set(cache_key, data, ttl=self.history_cache_ttl_seconds)
        return data

    def get_etf_nav(self, symbol: str) -> dict:
        cache_key = f"nav_{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not _SENTINEL:
            self._validate_timestamp_freshness(
                cached['timestamp'],
                source='mx_data.nav',
                max_age_seconds=self.max_nav_age_seconds,
            )
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
        cache_ttl = self._freshness_limited_ttl(
            default_ttl=60,
            timestamp=data['timestamp'],
            source='mx_data.nav',
            max_age_seconds=self.max_nav_age_seconds,
        )
        self.cache.set(cache_key, data, ttl=cache_ttl)
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

    def cache_policy(self) -> dict:
        return {
            'history_ttl_seconds': self.history_cache_ttl_seconds,
            'history_cache_hits': self.history_cache_hits,
            'history_cache_misses': self.history_cache_misses,
            'last_history_cache_key': self.last_history_cache_key,
            'last_history_cache_hit': self.last_history_cache_hit,
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

    def _record_history_cache_access(self, cache_key: str, *, hit: bool) -> None:
        self.last_history_cache_key = cache_key
        self.last_history_cache_hit = hit
        if hit:
            self.history_cache_hits += 1
        else:
            self.history_cache_misses += 1

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

        return {
            field: self._normalize_field(field, record[field], source)
            for field in required_fields
        }

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

    def _normalize_field(self, field: str, value, source: str):
        if field in self.TEXT_FIELDS:
            if not isinstance(value, str):
                self._raise_invalid_field(source, field, '必须是字符串')
            return value

        if field in self.INTEGER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, Integral):
                self._raise_invalid_field(source, field, '必须是非负整数')
            if value < 0:
                self._raise_invalid_field(source, field, '必须是非负整数')
            return int(value)

        if field in self.NON_NEGATIVE_NUMBER_FIELDS:
            number = self._normalize_number(field, value, source)
            if number < 0:
                self._raise_invalid_field(source, field, '必须大于等于 0')
            return number

        if field in self.SIGNED_NUMBER_FIELDS:
            return self._normalize_number(field, value, source)

        raise RuntimeError(
            f"字段 {field} 缺少校验规则；已知分类: "
            "TEXT_FIELDS, SIGNED_NUMBER_FIELDS, INTEGER_FIELDS, "
            "NON_NEGATIVE_NUMBER_FIELDS"
        )

    def _normalize_number(self, field: str, value, source: str) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            self._raise_invalid_field(source, field, '必须是有限数字')
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise DataFetchError(
                f"{source} 字段 {field} 必须是有限数字",
                error_code='INVALID_FIELD_VALUE',
                source=source,
            ) from exc
        if not math.isfinite(number):
            self._raise_invalid_field(source, field, '必须是有限数字')
        return number

    def _raise_invalid_field(self, source: str, field: str, reason: str) -> None:
        raise DataFetchError(
            f"{source} 字段 {field} {reason}",
            error_code='INVALID_FIELD_VALUE',
            source=source,
        )

    def _validate_timestamp_freshness(
        self,
        timestamp: str,
        source: str,
        max_age_seconds,
    ) -> float | None:
        if max_age_seconds is None:
            return None
        if not timestamp:
            raise DataFetchError(
                f"{source} timestamp 不能为空",
                error_code='MISSING_TIMESTAMP',
                source=source,
            )

        parsed = self._parse_timestamp(timestamp, source)
        now = datetime.now(parsed.tzinfo)
        age_seconds = (now - parsed).total_seconds()
        future_skew = self.max_timestamp_future_skew_seconds
        if future_skew is not None and age_seconds < -future_skew:
            raise DataFetchError(
                f"{source} timestamp 超出允许的未来偏移: timestamp={timestamp}",
                error_code='FUTURE_DATA',
                source=source,
            )
        if age_seconds > max_age_seconds:
            raise DataFetchError(
                f"{source} 数据已过期: timestamp={timestamp}",
                error_code='STALE_DATA',
                source=source,
            )
        return age_seconds

    def _parse_timestamp(self, timestamp: str, source: str) -> datetime:
        try:
            normalized = (
                timestamp[:-1] + '+00:00'
                if timestamp.endswith('Z')
                else timestamp
            )
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise DataFetchError(
                f"{source} timestamp 不是合法 ISO 时间: {timestamp}",
                error_code='INVALID_TIMESTAMP',
                source=source,
            ) from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self.timestamp_timezone)
        return parsed

    def _parse_timezone_offset(self, offset: str) -> timezone:
        if not isinstance(offset, str):
            raise ValueError('timestamp_timezone_offset 必须是字符串')
        if len(offset) != 6 or offset[0] not in '+-' or offset[3] != ':':
            raise ValueError('timestamp_timezone_offset 必须是 +HH:MM 或 -HH:MM')
        try:
            hours = int(offset[1:3])
            minutes = int(offset[4:6])
        except ValueError as exc:
            raise ValueError(
                'timestamp_timezone_offset 必须是 +HH:MM 或 -HH:MM'
            ) from exc
        if hours > 23 or minutes > 59:
            raise ValueError('timestamp_timezone_offset 超出合法时区偏移范围')
        sign = 1 if offset[0] == '+' else -1
        return timezone(sign * timedelta(hours=hours, minutes=minutes))

    def _freshness_limited_ttl(
        self,
        default_ttl: int,
        timestamp: str,
        source: str,
        max_age_seconds,
    ):
        age_seconds = self._validate_timestamp_freshness(
            timestamp,
            source,
            max_age_seconds,
        )
        if age_seconds is None:
            return default_ttl
        return min(default_ttl, max(0, max_age_seconds - age_seconds))
