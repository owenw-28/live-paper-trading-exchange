import json
from decimal import Decimal
from pathlib import Path

import pytest

from apps.marketdata.book import OrderBook, checksum_digits

FIXTURE = Path(__file__).parent / "fixtures" / "kraken_book_sample.jsonl"


def load_book_messages() -> list[dict]:
    with FIXTURE.open() as f:
        messages = [json.loads(line, parse_float=Decimal) for line in f]
    return [m for m in messages if m.get("channel") == "book"]


def replay(messages: list[dict]) -> list[tuple[int, int]]:
    "Apply book messages in order; return (Kraken's checksum, our checksum) for each."
    books: dict[str, OrderBook] = {}
    results = []
    for message in messages:
        for data in message["data"]:
            symbol = data["symbol"]
            if message["type"] == "snapshot":
                books[symbol] = OrderBook(symbol)
                books[symbol].apply_snapshot(data["bids"], data["asks"])
            else:
                books[symbol].apply_update(data["bids"], data["asks"])
            results.append((data["checksum"], books[symbol].checksum()))
    return results


def level(price: str, qty: str) -> dict[str, Decimal]:
    return {"price": Decimal(price), "qty": Decimal(qty)}


def test_recorded_feed_checksums_all_match():
    results = replay(load_book_messages())

    mismatches = [i for i, (expected, actual) in enumerate(results) if expected != actual]
    assert len(results) > 100
    assert mismatches == []


def test_dropped_update_is_detected():
    messages = load_book_messages()
    first_update = next(i for i, m in enumerate(messages) if m["type"] == "update")
    del messages[first_update]

    results = replay(messages)

    assert any(expected != actual for expected, actual in results)


def test_corrupted_update_is_detected():
    messages = load_book_messages()
    update = next(m for m in messages if m["type"] == "update" and m["data"][0]["bids"])
    update["data"][0]["bids"][0]["qty"] += Decimal("0.00000001")

    results = replay(messages)

    assert any(expected != actual for expected, actual in results)


def test_zero_quantity_removes_price_level():
    book = OrderBook("BTC/USD")
    book.apply_snapshot(bids=[level("100.0", "1.0"), level("99.0", "2.0")], asks=[])

    book.apply_update(bids=[level("100.0", "0")], asks=[])

    assert book.top_bids() == [(Decimal("99.0"), Decimal("2.0"))]


def test_book_is_truncated_to_depth():
    book = OrderBook("BTC/USD", depth=2)
    book.apply_snapshot(bids=[level("100", "1"), level("99", "1")], asks=[])

    book.apply_update(bids=[level("101", "1")], asks=[])

    assert list(book.bids) == [Decimal("101"), Decimal("100")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.00006120", "6120"), ("82074.9", "820749"), ("1.00000000", "100000000")],
)
def test_checksum_digits(value, expected):
    assert checksum_digits(Decimal(value)) == expected


def test_checksum_covers_only_the_top_ten_levels_at_any_depth():
    bids = [level(str(1000 - n), "1") for n in range(15)]
    asks = [level(str(1001 + n), "1") for n in range(15)]
    deep, shallow = OrderBook("BTC/USD", depth=100), OrderBook("BTC/USD", depth=10)
    deep.apply_snapshot(bids, asks)
    shallow.apply_snapshot(bids, asks)

    assert len(deep.top_bids()) == 15
    assert deep.checksum() == shallow.checksum()
