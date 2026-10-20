"""Long-running Kraken ingestor: one WebSocket connection, verified books, automatic recovery."""

import asyncio
import logging
import random
import time

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.trace import SpanKind
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from apps.marketdata.events import book_event, encode, trade_event
from apps.marketdata.kraken import (
    URL,
    BookTracker,
    parse_message,
    subscribe_message,
    unsubscribe_message,
)
from apps.marketdata.publisher import Publisher
from apps.marketdata.topics import BOOK, KRAKEN_RAW, TRADES, instrument_key

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)
tracer = trace.get_tracer(__name__)

messages_received = meter.create_counter(
    "marketdata.messages", description="Messages received from the venue"
)

reconnects = meter.create_counter(
    "marketdata.reconnects", description="Times the venue connection was re-established"
)

resyncs = meter.create_counter(
    "marketdata.resyncs", description="Books discarded after a checksum mismatch"
)

malformed = meter.create_counter(
    "marketdata.malformed", description="Messages from the venue that were not valid JSON"
)


class StaleFeedError(Exception):
    """No message arrived within the staleness window."""


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Exponential backoff with full jitter: a random delay up to base * 2^(attempt - 1)."""
    return random.uniform(0, min(cap, base * 2 ** (attempt - 1)))


class KrakenIngestor:
    def __init__(
        self,
        symbols: list[str],
        publisher: Publisher,
        depth: int = 10,
        url: str = URL,
        stale_after: float = 10.0,
        healthy_after: float = 60.0,
    ) -> None:
        self.symbols = symbols
        self.publisher = publisher
        self.depth = depth
        self.url = url
        self.stale_after = stale_after
        self.healthy_after = healthy_after
        self.tracker = BookTracker(depth)
        self._last_message_at = time.monotonic()
        meter.create_observable_gauge(
            "marketdata.seconds_since_last_message",
            callbacks=[self._observe_staleness],
            description="Seconds since the venue last sent any message",
        )

    async def run(self) -> None:
        """Stay connected forever, reconnecting with backoff whenever a session ends."""
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                await self._session()
            except (OSError, ConnectionClosed, InvalidHandshake, StaleFeedError) as exc:
                logger.warning("Kraken session ended: %r", exc)
            if time.monotonic() - started >= self.healthy_after:
                attempt = 0
            attempt += 1
            delay = backoff_delay(attempt)
            logger.info("Reconnecting to Kraken in %.1fs (attempt %d)", delay, attempt)
            await asyncio.sleep(delay)
            reconnects.add(1, {"venue": "kraken"})

    async def _session(self) -> None:
        self.tracker = BookTracker(self.depth)
        async with connect(self.url) as ws:
            logger.info("Connected to Kraken")
            await ws.send(subscribe_message("book", self.symbols, depth=self.depth))
            await ws.send(subscribe_message("trade", self.symbols))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.stale_after)
                except TimeoutError:
                    raise StaleFeedError(f"no message for {self.stale_after}s") from None
                self._last_message_at = time.monotonic()
                await self._handle(ws, raw)

    async def _handle(self, ws, raw: str) -> None:
        try:
            message = parse_message(raw)
        except ValueError:
            self.publisher.publish(KRAKEN_RAW.name, None, raw.encode())
            malformed.add(1, {"venue": "kraken"})
            logger.error("Unparseable message from Kraken: %.200s", raw)
            return
        channel = message.get("channel") or message.get("method", "unknown")
        messages_received.add(1, {"venue": "kraken", "channel": channel})
        self.publisher.publish(KRAKEN_RAW.name, _raw_key(message), raw.encode())

        if message.get("method") in ("subscribe", "unsubscribe") and not message.get("success"):
            logger.error("Kraken rejected %s: %s", message["method"], message.get("error"))
        elif channel == "book":
            with tracer.start_as_current_span("kraken book", kind=SpanKind.PRODUCER):
                await self._handle_book(ws, message)
        elif channel == "trade":
            with tracer.start_as_current_span("kraken trade", kind=SpanKind.PRODUCER):
                for trade in message["data"]:
                    key = instrument_key("kraken", trade["symbol"])
                    self.publisher.publish(TRADES.name, key, encode(trade_event("kraken", trade)))

    async def _handle_book(self, ws, message: dict) -> None:
        failed = self.tracker.handle(message)
        for data in message["data"]:
            book = self.tracker.books.get(data["symbol"])
            if book is not None:
                event = book_event("kraken", book, data["timestamp"])
                self.publisher.publish(
                    BOOK.name, instrument_key("kraken", book.symbol), encode(event)
                )
        for symbol in failed:
            logger.warning("Checksum mismatch for %s; resyncing", symbol)
            resyncs.add(1, {"venue": "kraken", "symbol": symbol})
            await ws.send(unsubscribe_message("book", [symbol], depth=self.depth))
            await ws.send(subscribe_message("book", [symbol], depth=self.depth))

    def _observe_staleness(self, options: CallbackOptions):
        yield Observation(time.monotonic() - self._last_message_at, {"venue": "kraken"})


def _raw_key(message: dict) -> str | None:
    data = message.get("data")
    if isinstance(data, list) and data and "symbol" in data[0]:
        return instrument_key("kraken", data[0]["symbol"])
    return None
