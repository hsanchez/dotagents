# Annotated change

`src/cache.py:2` concatenates identifiers without a delimiter. Inputs `("ab", "c")` and
`("a", "bc")` collide. `tests/test_cache.py:4` covers only one example and misses the collision.
