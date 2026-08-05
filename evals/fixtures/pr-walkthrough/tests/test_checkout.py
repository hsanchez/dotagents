from src.checkout import checkout


def test_discount_is_applied() -> None:
    assert checkout(500, 125) == 375
