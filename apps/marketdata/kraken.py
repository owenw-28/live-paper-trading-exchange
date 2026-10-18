"""Kraken WebSocket v2 protocol: message parsing, subscriptions and book tracking."""

import json
from decimal import Decimal

from apps.marketdata.book import OrderBook

URL = "wss://ws.kraken.com/v2"


def parse_message(raw: str) -> dict:
    """Parse a raw Kraken message, keeping prices and quantities exact as Decimals."""
    return json.loads(raw, parse_float=Decimal)


def subscribe_message(channel: str, symbols: list[str], **params) -> str:
    return json.dumps(
        {"method": "subscribe", "params": {"channel": channel, "symbol": symbols, **params}}
    )


def unsubscribe_message(channel: str, symbols: list[str], **params) -> str:
    return json.dumps(
        {"method": "unsubscribe", "params": {"channel": channel, "symbol": symbols, **params}}
    )


class BookTracker:
    """Keeps one verified OrderBook per symbol from Kraken book messages.

    A symbol is only tracked between a snapshot and the first checksum mismatch. After a
    mismatch its book is discards, and updates are ignored until a fresh snapshot arrives.
    """

    def __init__(self, depth: int = 10) -> None:
        self.depth = depth
        self.books: dict[str, OrderBook] = {}

    def handle(self, message: dict) -> list[str]:
        """Apply one book message. Return the symbols whose books failed verification."""
        failed = []
        for data in message["data"]:
            symbol = data["symbol"]
            if message["type"] == "snapshot":
                self.books[symbol] = OrderBook(symbol, self.depth)
                self.books[symbol].apply_snapshot(data["bids"], data["asks"])
            elif symbol in self.books:
                self.books[symbol].apply_update(data["bids"], data["asks"])
            else:
                continue  # waiting for a snapshot after a resync
            if self.books[symbol].checksum() != data["checksum"]:
                del self.books[symbol]
                failed.append(symbol)
        return failed
