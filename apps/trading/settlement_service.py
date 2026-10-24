"""Runs settlement against Kafka: outcomes from orders.events into Postgres.

Offsets are committed only after the database transactions they caused have committed. A
crash in between redelivers those outcomes, and settle() skips the ones already applied.
All state is in Postgres, so several copies can run in one consumer group; no leader needed.
"""

import json
import logging
from collections.abc import Callable

from confluent_kafka import Consumer, Message, TopicPartition
from opentelemetry import metrics, trace
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind

from apps.core.kafka import text_headers
from apps.trading.models import Order
from apps.trading.notifications import notify_user
from apps.trading.settlement import settle
from apps.trading.topics import ORDER_EVENTS

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)
tracer = trace.get_tracer(__name__)

applied_counter = meter.create_counter("settlement.applied", description="Outcomes applied")
skipped_counter = meter.create_counter(
    "settlement.skipped", description="Outcomes skipped: repeats, or superseded by a final one"
)
order_latency = meter.create_histogram(
    "order.placed_to_settled",
    unit="s",
    description="Time from an order being placed to its final status being committed",
    explicit_bucket_boundaries_advisory=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 10],
)


class SettlementService:
    def __init__(self, consumer: Consumer, notify: Callable[[Order], None] = notify_user) -> None:
        self.consumer = consumer
        self.notify = notify

    def start(self) -> None:
        self.consumer.subscribe([ORDER_EVENTS.name])

    def step(self) -> int:
        """Settle one batch of outcomes, then commit. Returns how many messages were handled."""
        offsets: dict[int, int] = {}
        messages = self._next_batch()
        for message in messages:
            if message.error():
                logger.error("Consumer error: %s", message.error())
                continue
            self._apply(message)
            partition, offset = message.partition(), message.offset()
            if partition is not None and offset is not None:
                offsets[partition] = offset + 1
        if offsets:
            commits = [TopicPartition(ORDER_EVENTS.name, p, o) for p, o in offsets.items()]
            self.consumer.commit(offsets=commits, asynchronous=False)
        return len(messages)

    def _next_batch(self) -> list[Message]:
        first = self.consumer.poll(0.5)
        if first is None:
            return []
        return [first, *self.consumer.consume(num_messages=199, timeout=0)]

    def _apply(self, message: Message) -> None:
        event = json.loads(message.value() or b"{}")
        with tracer.start_as_current_span(
            f"settle {event['type']}",
            context=extract(text_headers(message)),
            kind=SpanKind.CONSUMER,
        ):
            order = settle(event)
        if order is None:
            skipped_counter.add(1, {"type": event["type"]})
            return
        applied_counter.add(1, {"type": event["type"]})
        self.notify(order)  # settle() has committed, so the browser never hears of a rollback
        if order.settled_at is not None:
            order_latency.record(
                (order.settled_at - order.created_at).total_seconds(),
                {"status": order.status, "order_type": order.order_type},
            )
