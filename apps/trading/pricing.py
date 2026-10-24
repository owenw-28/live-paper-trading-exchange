"""How much to reserve for an order."""

from decimal import ROUND_UP, Decimal

Level = tuple[Decimal, Decimal]  # (price, quantity)


def round_up(amount: Decimal, places: int) -> Decimal:
    """Round up to `places` decimals, so a reservation always covers the full cost."""
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_UP)


def cost_to_buy(asks: list[Level], quantity: Decimal) -> Decimal | None:
    """Cost of buying `quantity` by walking the asks, best first. None if they run out."""
    remaining, cost = quantity, Decimal(0)
    for price, available in asks:
        take = min(remaining, available)
        cost += take * price
        remaining -= take
        if remaining == 0:
            return cost
    return None


def limit_buy_reservation(quantity: Decimal, limit_price: Decimal, fee_rate: Decimal) -> Decimal:
    """A limit buy never pays more than its limit, so this always covers it, fee included."""
    return round_up(quantity * limit_price * (1 + fee_rate), 2)


def market_buy_reservation(
    asks: list[Level], quantity: Decimal, fee_rate: Decimal, buffer: Decimal
) -> Decimal | None:
    """Today's cost plus a buffer for the price moving before the fill. None if too large."""
    cost = cost_to_buy(asks, quantity)
    if cost is None:
        return None
    return round_up(cost * (1 + buffer) * (1 + fee_rate), 2)
