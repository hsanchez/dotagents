def cart_total(prices: list[int]) -> int:
    if not prices:
        return 0
    return sum(prices)
