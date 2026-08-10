def checkout(total_cents: int, discount_cents: int) -> int:
    return max(0, total_cents - discount_cents)
