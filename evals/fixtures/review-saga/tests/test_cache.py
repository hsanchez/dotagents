from src.cache import cache_key


def test_cache_key() -> None:
    assert cache_key("ab", "c") == "abc"
