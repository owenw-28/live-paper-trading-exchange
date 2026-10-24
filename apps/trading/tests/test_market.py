import time
from decimal import Decimal

from fakeredis import FakeRedis

from apps.marketdata.live import book_key, frame
from apps.trading import market


def store_book(redis: FakeRedis, age_s: float) -> None:
    event = {
        "symbol": "BTC/USD",
        "bids": [["99.9", "1"]],
        "asks": [["100.0", "0.5"], ["100.1", "2.0"]],
        "ingested_at_ns": time.time_ns() - int(age_s * 1e9),
    }
    redis.set(book_key("kraken:BTC/USD"), frame("book", event))


def test_reads_fresh_asks_as_decimals(monkeypatch):
    redis = FakeRedis(decode_responses=True)
    monkeypatch.setattr(market, "_client", lambda: redis)
    store_book(redis, age_s=1)

    assert market.latest_asks("kraken:BTC/USD") == [
        (Decimal("100.0"), Decimal("0.5")),
        (Decimal("100.1"), Decimal("2.0")),
    ]


def test_refuses_a_stale_book(monkeypatch):
    redis = FakeRedis(decode_responses=True)
    monkeypatch.setattr(market, "_client", lambda: redis)
    store_book(redis, age_s=market.MAX_BOOK_AGE_S + 1)

    assert market.latest_asks("kraken:BTC/USD") is None


def test_no_book_at_all(monkeypatch):
    monkeypatch.setattr(market, "_client", lambda: FakeRedis(decode_responses=True))

    assert market.latest_asks("kraken:BTC/USD") is None
