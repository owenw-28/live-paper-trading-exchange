"""Fans verified books and trades out from Redpanda to Redis and to clients' Channels groups.

Unlike the archiver, this consumer always starts from the newest message: clients want the
current market, and every book event is a complete book, so skipping old ones loses nothing.
"""

import asyncio
import json
import logging
import time

from confluent_kafka import OFFSET_END, Consumer, Message, TopicPartition
from opentelemetry import metrics, trace
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind

from apps.core.kafka import text_headers
from apps.marketdata.latency import LATENCY_BUCKETS_S
from apps.marketdata.live import DISPLAY_DEPTH, LiveState, frame, group_name
from apps.marketdata.topics import BOOK, TRADES

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)
tracer = trace.get_tracer(__name__)

delivered = meter.create_counter("fanout.delivered", description="Events sent to Redis and groups")
coalesced = meter.create_counter(
    "fanout.books_coalesced",
    description="Books skipped because a newer book for the same instrument was in the batch",
)
ingest_to_broadcast = meter.create_histogram(
    "marketdata.ingest_to_broadcast",
    unit="s",
    description="Time from the ingestor receiving an event to the fan-out broadcasting it",
    explicit_bucket_boundaries_advisory=LATENCY_BUCKETS_S,
)


class Fanout:
    def __init__(self, consumer: Consumer, live: LiveState, channel_layer, max_batch: int = 500):
        self.consumer = consumer
        self.live = live
        self.channel_layer = channel_layer
        self.max_batch = max_batch
        self._stopping = False

    async def run(self) -> None:
        self.consumer.subscribe([BOOK.name, TRADES.name], on_assign=_start_at_newest)
        loop = asyncio.get_running_loop()
        while not self._stopping:
            messages = await loop.run_in_executor(None, self._next_batch)
            await self.handle_batch(messages)
        self.consumer.close()

    def stop(self) -> None:
        self._stopping = True

    def _next_batch(self) -> list[Message]:
        """Wait for one message, then take whatever else has already arrived, without waiting."""
        first = self.consumer.poll(0.5)
        if first is None:
            return []
        return [first, *self.consumer.consume(num_messages=self.max_batch - 1, timeout=0)]

    async def handle_batch(self, messages: list[Message]) -> None:
        latest_books: dict[str, Message] = {}
        trades: list[Message] = []
        for message in messages:
            if message.error():
                logger.error("Consumer error: %s", message.error())
                continue
            key = message.key()
            if key is None or message.value() is None:
                logger.warning("Skipping message without key or value on %s", message.topic())
                continue
            if message.topic() == BOOK.name:
                instrument = key.decode()
                if instrument in latest_books:
                    coalesced.add(1, {"instrument": instrument})
                latest_books[instrument] = message
            elif message.topic() == TRADES.name:
                trades.append(message)
        for message in trades:
            await self._deliver("trade", message)
        for message in latest_books.values():
            await self._deliver("book", message)

    async def _deliver(self, kind: str, message: Message) -> None:
        key, value = message.key(), message.value()
        assert key is not None and value is not None  # handle_batch skipped any without
        instrument = key.decode()
        event = json.loads(value)
        if kind == "book":  # browsers only show the top of the book
            text = frame(
                kind,
                {
                    **event,
                    "bids": event["bids"][:DISPLAY_DEPTH],
                    "asks": event["asks"][:DISPLAY_DEPTH],
                },
            )
        else:
            text = frame(kind, event)
        carrier = text_headers(message)
        with tracer.start_as_current_span(
            f"fanout {kind}", context=extract(carrier), kind=SpanKind.CONSUMER
        ):
            if kind == "book":
                await self.live.save_book(instrument, text)
                await self.live.save_depth(instrument, value.decode())
            else:
                await self.live.save_trade(instrument, text)
            await self.channel_layer.group_send(
                group_name(instrument),
                {
                    "type": f"market.{kind}",
                    "instrument": instrument,
                    "frame": text,
                    "ingested_at_ns": event["ingested_at_ns"],
                },
            )
        delivered.add(1, {"kind": kind})
        latency_s = (time.time_ns() - event["ingested_at_ns"]) / 1e9
        ingest_to_broadcast.record(latency_s, {"kind": kind})


def _start_at_newest(consumer: Consumer, partitions: list[TopicPartition]) -> None:
    for tp in partitions:
        tp.offset = OFFSET_END
    consumer.assign(partitions)
