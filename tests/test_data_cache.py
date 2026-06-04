from data.data_cache import DataCache, _SENTINEL


def test_cache_respects_explicit_zero_ttl():
    cache = DataCache(default_ttl=300)

    cache.set('quote', {'price': 4.0}, ttl=0)

    assert cache.get('quote') is _SENTINEL
