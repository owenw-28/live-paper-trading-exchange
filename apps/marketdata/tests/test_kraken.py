from decimal import Decimal
from pathlib import Path

from apps.marketdata.ingestor import backoff_delay
from apps.marketdata.kraken import BookTracker, parse_message

FIXTURE = Path(__file__).parent / "fixtures" / "kraken_book_sample.jsonl"


def book_messages() -> list[dict]:
    with FIXTURE.open() as f:
        messages = [parse_message(line) for line in f]
    return [m for m in messages if m.get("channel") == "book"]


def test_parse_message_keeps_exact_decimals():
    message = parse_message('{"qty": 0.00006120}')

    assert message["qty"] == Decimal("0.00006120")
    assert str(message["qty"]) == "0.00006120"


def test_tracker_verifies_whole_recording_without_resyncs():
    tracker = BookTracker()

    failed = [symbol for message in book_messages() for symbol in tracker.handle(message)]

    assert failed == []
    assert set(tracker.books) == {"BTC/USD", "ETH/USD"}


def test_tracker_drops_book_on_mismatch_and_waits_for_snapshot():
    messages = book_messages()
    snapshots = [m for m in messages if m["type"] == "snapshot"]
    updates = [m for m in messages if m["type"] == "update"]
    bad = updates[0]
    bad["data"][0]["checksum"] += 1
    symbol = bad["data"][0]["symbol"]
    tracker = BookTracker()
    for snapshot in snapshots:
        tracker.handle(snapshot)

    failed = tracker.handle(bad)
    later_update = next(m for m in updates[1:] if m["data"][0]["symbol"] == symbol)
    failed_later = tracker.handle(later_update)

    assert failed == [symbol]
    assert symbol not in tracker.books
    assert failed_later == []
    assert symbol not in tracker.books


def test_backoff_delay_grows_exponentially_and_is_capped():
    for attempt, ceiling in [(1, 1.0), (2, 2.0), (3, 4.0), (7, 60.0), (20, 60.0)]:
        delays = [backoff_delay(attempt, base=1.0, cap=60.0) for _ in range(200)]
        assert all(0 <= d <= ceiling for d in delays)
        assert max(delays) > ceiling / 2
