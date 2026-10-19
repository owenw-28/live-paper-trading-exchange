"""WebSocket endpoint streaming live books and trades to browsers, one consumer per client."""

import asyncio
import time
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from opentelemetry import metrics

from apps.marketdata.conflation import ClientQueue
from apps.marketdata.live import LiveState, group_name
from apps.marketdata.topics import instrument_key

meter = metrics.get_meter(__name__)

connections = meter.create_up_down_counter("ws.connections", description="Open market sockets")
frames_sent = meter.create_counter("ws.frames_sent", description="Frames sent to clients")
books_conflated = meter.create_counter(
    "ws.books_conflated", description="Books replaced by a newer one before they were sent"
)
trades_dropped = meter.create_counter(
    "ws.trades_dropped", description="Trades dropped because a client's queue was full"
)
ingest_to_send = meter.create_histogram(
    "marketdata.ingest_to_send",
    unit="s",
    description="Time from the ingestor receiving an event to it being sent to a client",
    explicit_bucket_boundaries_advisory=[
        0.0005,
        0.001,
        0.002,
        0.003,
        0.005,
        0.0075,
        0.01,
        0.015,
        0.02,
        0.03,
        0.05,
        0.075,
        0.1,
        0.2,
        0.5,
        1.0,
    ],
)


class MarketDataConsumer(AsyncWebsocketConsumer):
    def __init__(self, live: LiveState, **kwargs) -> None:
        super().__init__(**kwargs)
        self.live = live
        self.instruments: list[str] = []
        self.sender: asyncio.Task | None = None

    async def connect(self) -> None:
        symbols = _requested_symbols(self.scope["query_string"])
        if symbols is None:
            await self.close()
            return
        self.instruments = [instrument_key("kraken", symbol) for symbol in symbols]
        self.queue = ClientQueue(1 / settings.MARKETDATA_MAX_BOOKS_PER_SECOND)
        self.wakeup = asyncio.Event()
        await self.accept()
        for instrument in self.instruments:
            await self.channel_layer.group_add(group_name(instrument), self.channel_name)
        for instrument in self.instruments:
            for text in await self.live.snapshot(instrument):
                await self.send(text_data=text)
        self.sender = asyncio.create_task(self._send_loop())
        connections.add(1)

    async def disconnect(self, code: int) -> None:
        if self.sender is None:
            return
        self.sender.cancel()
        for instrument in self.instruments:
            await self.channel_layer.group_discard(group_name(instrument), self.channel_name)
        connections.add(-1)

    async def market_book(self, message: dict) -> None:
        if self.queue.put_book(message["instrument"], message["frame"], message["ingested_at_ns"]):
            books_conflated.add(1)
        self.wakeup.set()

    async def market_trade(self, message: dict) -> None:
        if self.queue.put_trade(message["frame"], message["ingested_at_ns"]):
            trades_dropped.add(1)
        self.wakeup.set()

    async def _send_loop(self) -> None:
        while True:
            frames, wait_s = self.queue.drain(time.monotonic())
            for frame in frames:
                await self.send(text_data=frame.text)
                frames_sent.add(1, {"kind": frame.kind})
                latency_s = (time.time_ns() - frame.ingested_at_ns) / 1e9
                ingest_to_send.record(latency_s, {"kind": frame.kind})
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=wait_s)
            except TimeoutError:
                pass
            self.wakeup.clear()


def _requested_symbols(query_string: bytes) -> list[str] | None:
    """Symbols from ?symbols=BTC/USD,ETH/USD (default: all). None if any isn't supported."""
    query = parse_qs(query_string.decode())
    requested = query.get("symbols", [",".join(settings.MARKETDATA_SYMBOLS)])[0].split(",")
    if not requested or not set(requested) <= set(settings.MARKETDATA_SYMBOLS):
        return None
    return requested
