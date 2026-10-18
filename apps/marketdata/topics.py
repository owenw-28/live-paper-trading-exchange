"""Redpanda topics for market data. Topics are keyed by venue and symbol."""

from dataclasses import dataclass

HOUR_MS = 60 * 60 * 1000


@dataclass(frozen=True)
class Topic:
    name: str
    partitions: int
    retention_ms: int


KRAKEN_RAW = Topic("marketdata.kraken.raw", partitions=6, retention_ms=7 * 24 * HOUR_MS)
BOOK = Topic("marketdata.book", partitions=6, retention_ms=HOUR_MS)
TRADES = Topic("marketdata.trades", partitions=6, retention_ms=7 * 24 * HOUR_MS)

ALL_TOPICS = [KRAKEN_RAW, BOOK, TRADES]


def instrument_key(venue: str, symbol: str) -> str:
    return f"{venue}:{symbol}"
