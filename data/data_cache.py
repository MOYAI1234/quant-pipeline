import time


class DataCache:

    def __init__(self, default_ttl: int = 300):
        self._cache = {}
        self._default_ttl = default_ttl

    def get(self, key: str):
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry['expire_at']:
                return entry['value']
            del self._cache[key]
        return None

    def set(self, key: str, value, ttl: int = None):
        self._cache[key] = {
            'value': value,
            'expire_at': time.time() + (ttl or self._default_ttl)
        }

    def delete(self, key: str):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()

    def has(self, key: str) -> bool:
        return self.get(key) is not None
