import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path

from apps.marketdata.book import OrderBook
from apps.marketdata.events import book_event, encode
from apps.marketdata.ingestor import KrakenIngestor

FIXTURE = Path(__file__).parent / "fixtures" / "kraken_book_sample.jsonl"


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None, dict]] = []

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        try:
            decoded = json.loads(value)
        except ValueError:
            decoded = value.decode()  # malformed messages are archived as raw text
        self.sent.append((topic, key, decoded))

    def on(self, topic: str) -> list[tuple[str | None, dict]]:
        return [(key, value) for t, key, value in self.sent if t == topic]


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))


def feed(raw_lines: list[str]) -> tuple[FakePublisher, FakeWebSocket]:
    publisher, ws = FakePublisher(), FakeWebSocket()
    ingestor = KrakenIngestor(symbols=["BTC/USD", "ETH/USD"], publisher=publisher)

    async def run() -> None:
        for raw in raw_lines:
            await ingestor._handle(ws, raw)

    asyncio.run(run())
    return publisher, ws


def raw_lines() -> list[str]:
    return FIXTURE.read_text().splitlines()


def test_book_event_lists_best_prices_first_as_exact_strings():
    book = OrderBook("BTC/USD")
    book.apply_snapshot(
        bids=[
            {"price": Decimal("99.0"), "qty": Decimal("2.0")},
            {"price": Decimal("100.0"), "qty": Decimal("0.00006120")},
        ],
        asks=[{"price": Decimal("101.0"), "qty": Decimal("1.0")}],
    )

    event = json.loads(encode(book_event("kraken", book, "2026-10-18T10:00:00Z")))

    assert event["bids"] == [["100.0", "0.00006120"], ["99.0", "2.0"]]
    assert event["asks"] == [["101.0", "1.0"]]
    assert event["symbol"] == "BTC/USD"


def test_every_raw_message_is_archived_and_every_verified_book_published():
    lines = raw_lines()

    publisher, ws = feed(lines)

    messages = [json.loads(line) for line in lines]
    book_updates = sum(len(m["data"]) for m in messages if m.get("channel") == "book")
    assert len(publisher.on("marketdata.kraken.raw")) == len(lines)
    assert len(publisher.on("marketdata.book")) == book_updates
    assert {key for key, _ in publisher.on("marketdata.book")} == {
        "kraken:BTC/USD",
        "kraken:ETH/USD",
    }
    assert ws.sent == []


def test_no_book_published_for_symbol_between_mismatch_and_new_snapshot():
    lines = raw_lines()
    first_btc_update = next(
        i
        for i, line in enumerate(lines)
        if '"type":"update"' in line and '"symbol":"BTC/USD"' in line and '"channel":"book"' in line
    )
    lines[first_btc_update] = re.sub(r'"checksum":(\d+)', '"checksum":1', lines[first_btc_update])

    publisher, ws = feed(lines)

    assert [m["method"] for m in ws.sent] == ["unsubscribe", "subscribe"]
    assert all(m["params"]["symbol"] == ["BTC/USD"] for m in ws.sent)
    btc_books = [v for k, v in publisher.on("marketdata.book") if k == "kraken:BTC/USD"]
    assert len(btc_books) == 1


def test_malformed_message_is_archived_without_crashing():
    publisher, _ = feed(["this is not JSON {"])

    assert publisher.on("marketdata.kraken.raw") == [(None, "this is not JSON {")]
    assert publisher.on("marketdata.book") == []
