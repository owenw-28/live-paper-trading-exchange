"""Runs the fill engine against Kafka: order commands and market data in, outcomes out.

At-least-once: command offsets are committed only after the outcomes they caused have been
acknowledged by Redpanda. After a crash, commands are decided again, and the engine also
re-reads every unfinished order from the database. Outcome ids are deterministic, so
settlement applies each order's outcome once.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from confluent_kafka import OFFSET_END, Consumer, Message, TopicPartition
from opentelemetry import metrics, trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind

from apps.core.kafka import text_headers
from apps.marketdata.topics import BOOK, TRADES, instrument_key
from apps.trading.engine import EngineOrder, FillEngine, Outcome
from apps.trading.models import Order, OrderStatus
from apps.trading.topics import ORDER_COMMANDS, ORDER_EVENTS

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)
tracer = trace.get_tracer(__name__)

LEADER_LOCK_ID = 74_210_002
WARM_UP_TIMEOUT_S = 10.0

outcomes_counter = meter.create_counter("engine.outcomes", description="Order outcomes decided")
decision_latency = meter.create_histogram(
    "engine.placed_to_outcome",
    unit="s",
    description="Time from an order being placed to the engine deciding its outcome",
    explicit_bucket_boundaries_advisory=[0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1],
)


class EngineFailure(Exception):
    """Outcomes weren't acknowledged; stop, and let a restart redo the work from durable state."""


class Producer(Protocol):
    def produce(
        self, topic: str, *, key: str, value: bytes, headers: list, on_delivery
    ) -> None: ...

    def flush(self, timeout: float) -> int: ...


def unfinished_orders() -> tuple[list[EngineOrder], set[int]]:
    """Every order the database says isn't finished, and which of them have a cancel pending."""
    rows = Order.objects.filter(status__in=[OrderStatus.PENDING, OrderStatus.OPEN]).order_by("id")
    orders = [
        EngineOrder(
            order_id=o.id,
            user_id=o.user_id,
            symbol=o.symbol,
            side=o.side,
            order_type=o.order_type,
            quantity=o.quantity,
            limit_price=o.limit_price,
            reserved_amount=o.reserved_amount,
        )
        for o in rows
    ]
    return orders, {o.id for o in rows if o.cancel_requested}


class EngineService:
    def __init__(
        self,
        consumer: Consumer,
        producer: Producer,
        engine: FillEngine,
        symbols: list[str],
        load_unfinished: Callable[[], tuple[list[EngineOrder], set[int]]] = unfinished_orders,
    ) -> None:
        self.consumer = consumer
        self.producer = producer
        self.engine = engine
        self.symbols = symbols
        self.load_unfinished = load_unfinished
        self.recovered = False
        self.warm_up_deadline: float | None = None  # starts when partitions are assigned
        self._paused: list[TopicPartition] = []

    def start(self) -> None:
        topics = [ORDER_COMMANDS.name, BOOK.name, TRADES.name]
        self.consumer.subscribe(topics, on_assign=self._on_assign)

    def step(self) -> int:
        """Handle one batch of messages. Returns how many outcomes were published."""
        outcomes: list[Outcome] = []
        offsets: dict[int, int] = {}
        for message in self._next_batch():
            if message.error():
                logger.error("Consumer error: %s", message.error())
                continue
            if message.topic() == BOOK.name:
                self._on_book(message)
            elif message.topic() == TRADES.name:
                outcomes += self._on_trade(message)
            elif message.topic() == ORDER_COMMANDS.name:
                outcomes += self._on_command(message)
                partition, offset = message.partition(), message.offset()
                if partition is not None and offset is not None:
                    offsets[partition] = offset + 1  # Kafka commits "the next offset to read"
        if not self.recovered and self._warm():
            outcomes += self._recover()
        self._publish(outcomes)
        if offsets:
            commits = [TopicPartition(ORDER_COMMANDS.name, p, o) for p, o in offsets.items()]
            self.consumer.commit(offsets=commits, asynchronous=False)
        return len(outcomes)

    def _on_assign(self, consumer: Consumer, partitions: list[TopicPartition]) -> None:
        for tp in partitions:
            if tp.topic != ORDER_COMMANDS.name:
                tp.offset = OFFSET_END  # market data: only the present matters
        consumer.assign(partitions)
        if self.warm_up_deadline is None:
            self.warm_up_deadline = time.monotonic() + WARM_UP_TIMEOUT_S
        if not self.recovered:  # hold orders until we have live prices to fill them against
            self._paused = [tp for tp in partitions if tp.topic == ORDER_COMMANDS.name]
            consumer.pause(self._paused)

    def _next_batch(self) -> list[Message]:
        first = self.consumer.poll(0.1)
        if first is None:
            return []
        return [first, *self.consumer.consume(num_messages=499, timeout=0)]

    def _on_book(self, message: Message) -> None:
        event = json.loads(message.value() or b"{}")
        self.engine.on_book(event["symbol"], event["bids"], event["asks"], event["ingested_at_ns"])

    def _on_trade(self, message: Message) -> list[Outcome]:
        event = json.loads(message.value() or b"{}")
        return self.engine.on_trade(event["symbol"], Decimal(event["price"]))

    def _on_command(self, message: Message) -> list[Outcome]:
        command = json.loads(message.value() or b"{}")
        carrier = text_headers(message)
        with tracer.start_as_current_span(
            f"engine {command['type']}", context=extract(carrier), kind=SpanKind.CONSUMER
        ):
            data = command["data"]
            if command["type"] == "order.placed":
                outcomes = self.engine.on_placed(EngineOrder.from_event(data))
            elif command["type"] == "order.cancel_requested":
                outcomes = self.engine.on_cancel(data["order_id"], data["symbol"])
            else:
                logger.warning("Unknown command %s", command["type"])
                outcomes = []
            headers: dict[str, str] = {}
            inject(headers)
        placed_at = datetime.fromisoformat(
            command["occurred_at"]
        ).timestamp()  # carries its UTC offset
        for outcome in outcomes:
            outcome.headers = headers
            decision_latency.record(max(0.0, time.time() - placed_at), {"type": outcome.type})
        return outcomes

    def _warm(self) -> bool:
        if self.warm_up_deadline is None:  # not assigned yet: a dead leader may still hold them
            return False
        has_prices = all(self.engine.fresh_book(s) is not None for s in self.symbols)
        return has_prices or time.monotonic() > self.warm_up_deadline

    def _recover(self) -> list[Outcome]:
        orders, cancels = self.load_unfinished()
        outcomes = self.engine.recover(orders, cancels)
        self.recovered = True
        if self._paused:
            self.consumer.resume(self._paused)
        logger.info("Recovered %d unfinished orders; accepting commands", len(orders))
        return outcomes

    def _publish(self, outcomes: list[Outcome]) -> None:
        if not outcomes:
            return
        failed: list[str] = []
        for outcome in outcomes:
            headers = {"event_id": outcome.event_id, "type": outcome.type, **outcome.headers}

            def on_delivery(error, message, event_id=outcome.event_id) -> None:
                if error is not None:
                    failed.append(event_id)

            self.producer.produce(
                ORDER_EVENTS.name,
                key=instrument_key("kraken", outcome.order.symbol),
                value=json.dumps(outcome.payload()).encode(),
                headers=list(headers.items()),
                on_delivery=on_delivery,
            )
            outcomes_counter.add(1, {"type": outcome.type})
        if self.producer.flush(10) or failed:
            raise EngineFailure(f"outcomes not acknowledged: {failed or 'flush timed out'}")
