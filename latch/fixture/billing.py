def discount_applies(seats: int, annual: bool) -> bool:
    if not annual:
        return False
    return seats >= 10


def annual_price_cents(seats: int) -> int:
    each = 800 if discount_applies(seats, True) else 1000
    return seats * each
