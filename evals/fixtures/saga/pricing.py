"""Simple order pricing helpers."""


def apply_discount(price: float, discount_percent: float) -> float:
  """Apply a percentage discount to a price."""
  return price - (price * discount_percent / 100)
