"""Level 2 order book for one symbol, kept in sync with Kraken's v2 book channel."""

import zlib
from decimal import Decimal

Level = dict[str, Decimal]


class OrderBook:
    def __init__(self, symbol: str, depth: int = 10) -> None:
        self.symbol = symbol
        self.depth = depth
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}

    def apply_snapshot(self, bids: list[Level], asks: list[Level]) -> None:
        self.bids.clear()
        self.asks.clear()
        self.apply_update(bids, asks)

    def apply_update(self, bids: list[Level], asks: list[Level]) -> None:
        _apply_levels(self.bids, bids)
        _apply_levels(self.asks, asks)
        self.bids = dict(self.top_bids())
        self.asks = dict(self.top_asks())

    def top_bids(self) -> list[tuple[Decimal, Decimal]]:
        return sorted(self.bids.items(), reverse=True)[: self.depth]

    def top_asks(self) -> list[tuple[Decimal, Decimal]]:
        return sorted(self.asks.items())[: self.depth]

    def checksum(self) -> int:
        levels = self.top_asks() + self.top_bids()
        payload = "".join(checksum_digits(price) + checksum_digits(qty) for price, qty in levels)
        return zlib.crc32(payload.encode())


def checksum_digits(value: Decimal) -> str:
    """Format a price or quantity the way Kraken's checksum expects: no '.', no leading zeros."""
    return format(value, "f").replace(".", "").lstrip("0")


def _apply_levels(side: dict[Decimal, Decimal], levels: list[Level]) -> None:
    for level in levels:
        if level["qty"] == 0:
            side.pop(level["price"], None)
        else:
            side[level["price"]] = level["qty"]
