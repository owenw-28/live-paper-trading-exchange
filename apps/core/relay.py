"""The read side of the transactional outbox: publish committed events to Redpanda, in order."""

import json
import logging
from typing import Protocol

from django.db.models import F
from django.utils import timezone
from opentelemetry import metrics, trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind

from apps.core.models import OutboxEvent

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)
tracer = trace.get_tracer(__name__)

LEADER_LOCK_ID = 74_210_001

published = meter.create_counter("outbox.published", description="Outbox events published")
publish_delay = meter.create_histogram(
    "outbox.publish_delay",
    unit="s",
    description="Time from an outbox event being written to it being published",
    explicit_bucket_boundaries_advisory=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 5],
)


class Producer(Protocol):
    """The parts of confluent_kafka.Producer the relay uses."""

    def produce(
        self, topic: str, *, key: str, value: bytes, headers: list, on_delivery
    ) -> None: ...

    def flush(self, timeout: float) -> int: ...


class Relay:
    def __init__(self, producer: Producer, batch_size: int = 500, flush_timeout_s: float = 10.0):
        self.producer = producer
        self.batch_size = batch_size
        self.flush_timeout_s = flush_timeout_s

    def publish_pending(self) -> int:
        """Publish the oldest unpublished events, then mark the delivered ones. Returns count."""
        events = list(
            OutboxEvent.objects.filter(published_at__isnull=True).order_by("created_at")[
                : self.batch_size
            ]
        )
        delivered: set = set()
        for event in events:
            self._produce(event, delivered)
        undelivered = self.producer.flush(self.flush_timeout_s)
        if undelivered:
            logger.warning("%d outbox events not acknowledged; they will be retried", undelivered)
        now = timezone.now()
        OutboxEvent.objects.filter(id__in=delivered).update(published_at=now)
        for event in events:
            if event.id in delivered:
                publish_delay.record(
                    (now - event.created_at).total_seconds(), {"topic": event.topic}
                )
        published.add(len(delivered))
        return len(delivered)

    def _produce(self, event: OutboxEvent, delivered: set) -> None:
        with tracer.start_as_current_span(
            f"outbox publish {event.payload['type']}",
            context=extract(event.headers),
            kind=SpanKind.PRODUCER,
        ):
            headers: dict[str, str] = {"event_id": str(event.id), "type": event.payload["type"]}
            inject(headers)

            def on_delivery(error, message, event_id=event.id) -> None:
                if error is None:
                    delivered.add(event_id)
                else:
                    logger.error("Publishing outbox event %s failed: %s", event_id, error)

            self.producer.produce(
                event.topic,
                key=event.key,
                value=json.dumps(event.payload).encode(),
                headers=list(headers.items()),
                on_delivery=on_delivery,
            )


def backlog() -> int:
    return OutboxEvent.objects.filter(published_at__isnull=True).count()


def oldest_unpublished_age_s() -> float:
    oldest = (
        OutboxEvent.objects.filter(published_at__isnull=True)
        .order_by("created_at")
        .values_list(F("created_at"), flat=True)
        .first()
    )
    return 0.0 if oldest is None else (timezone.now() - oldest).total_seconds()
