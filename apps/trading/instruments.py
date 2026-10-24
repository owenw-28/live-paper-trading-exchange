"""What can be traded, and the rules each order must follow."""

from dataclasses import dataclass
from decimal import Decimal

from apps.ledger.models import Asset


@dataclass(frozen=True)
class Instrument:
    symbol: str
    base: Asset  # what you buy or sell
    quote: Asset  # what you pay or receive
    quantity_step: Decimal
    min_quantity: Decimal
    price_tick: Decimal


INSTRUMENTS = {
    "BTC/USD": Instrument(
        "BTC/USD", Asset.BTC, Asset.USD, Decimal("0.00000001"), Decimal("0.0001"), Decimal("0.1")
    ),
    "ETH/USD": Instrument(
        "ETH/USD", Asset.ETH, Asset.USD, Decimal("0.00000001"), Decimal("0.001"), Decimal("0.01")
    ),
}
