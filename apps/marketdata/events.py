"""Venue-neutral market data events, as published to Redpanda."""

import json
import time

from apps.marketdata.book import OrderBook

SCHEMA_VERSION = 1


def book_event(venue: str, book: OrderBook, exchange_ts: str) -> dict:
    return {
        "v": SCHEMA_VERSION,
        "venue": venue,
        "symbol": book.symbol,
        "bids": [[str(price), str(qty)] for price, qty in book.top_bids()],
        "asks": [[str(price), str(qty)] for price, qty in book.top_asks()],
        "exchange_ts": exchange_ts,
        "ingested_at_ns": time.time_ns(),
    }


def trade_event(venue: str, trade: dict) -> dict:
    return {
        "v": SCHEMA_VERSION,
        "venue": venue,
        "symbol": trade["symbol"],
        "side": trade["side"],
        "price": str(trade["price"]),
        "qty": str(trade["qty"]),
        "trade_id": trade["trade_id"],
        "exchange_ts": trade["timestamp"],
        "ingested_at_ns": time.time_ns(),
    }


def encode(event: dict) -> bytes:
    return json.dumps(event, separators=(",", ":")).encode()
