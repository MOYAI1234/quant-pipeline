import time
from typing import Any

_SENTINEL = object()  # 用于区分"缓存不存在"和"缓存值为 None"


class DataCache:

    def __init__(self, default_ttl: int = 300):
        self._cache = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any:
        """获取缓存值，返回 _SENTINEL 表示缓存不存在"""
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry['expire_at']:
                return entry['value']
            # 过期删除
            del self._cache[key]
        return _SENTINEL

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存值"""
        effective_ttl = self._default_ttl if ttl is None else ttl
        self._cache[key] = {
            'value': value,
            'expire_at': time.time() + effective_ttl,
        }

    def delete(self, key: str):
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        """清空所有缓存"""
        self._cache.clear()

    def has(self, key: str) -> bool:
        """检查缓存是否存在且未过期"""
        return self.get(key) is not _SENTINEL

    def get_or_set(self, key: str, factory, ttl: int = None) -> Any:
        """获取缓存，不存在则调用 factory 创建并缓存"""
        value = self.get(key)
        if value is _SENTINEL:
            value = factory()
            self.set(key, value, ttl)
        return value
