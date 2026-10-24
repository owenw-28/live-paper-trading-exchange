"""How much to reserve for an order."""

from collections.abc import Callable
from decimal import ROUND_DOWN, ROUND_UP, Decimal

Level = tuple[Decimal, Decimal]  # (price, quantity)


def round_up(amount: Decimal, places: int) -> Decimal:
    """Round up to `places` decimals, so a reservation always covers the full cost."""
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_UP)


def round_down(amount: Decimal, places: int) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def take(
    levels: list[Level], quantity: Decimal, accept: Callable[[Decimal], bool] = lambda price: True
) -> list[Level] | None:
    """Fills from walking `levels` (best first) while `accept(price)`. None if they run out."""
    fills: list[Level] = []
    remaining = quantity
    for price, available in levels:
        if remaining == 0 or not accept(price):
            break
        size = min(remaining, available)
        fills.append((price, size))
        remaining -= size
    return fills if remaining == 0 else None


def notional(fills: list[Level]) -> Decimal:
    return sum((price * size for price, size in fills), Decimal(0))


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


def plain(amount: Decimal) -> str:
    """Decimal as text without scientific notation: 0.00000001, never 1E-8."""
    return format(amount, "f")


def buy_charge(gross: Decimal, fee_rate: Decimal) -> tuple[Decimal, Decimal]:
    """(amount, fee) a buyer pays for fills worth `gross`, each rounded up to the cent.

    Reservations use this same function, so a fill can never cost more than was reserved.
    """
    return round_up(gross, 2), round_up(gross * fee_rate, 2)


def limit_buy_reservation(quantity: Decimal, limit_price: Decimal, fee_rate: Decimal) -> Decimal:
    """A limit buy never pays more than its limit, so this always covers it, fee included."""
    return sum(buy_charge(quantity * limit_price, fee_rate), Decimal(0))


def market_buy_reservation(
    asks: list[Level], quantity: Decimal, fee_rate: Decimal, buffer: Decimal
) -> Decimal | None:
    """Today's cost plus a buffer for the price moving before the fill. None if too large."""
    cost = cost_to_buy(asks, quantity)
    if cost is None:
        return None
    return sum(buy_charge(cost * (1 + buffer), fee_rate), Decimal(0))
