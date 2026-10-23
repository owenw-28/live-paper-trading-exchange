"""Publishes messages to Redpanda, carrying the current trace context in message headers."""

import logging
from typing import Protocol

from confluent_kafka import Producer
from opentelemetry import metrics
from opentelemetry.propagate import inject

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)

published = meter.create_counter("marketdata.published", description="Messages handed to Kafka")
dropped = meter.create_counter(
    "marketdata.publish_dropped", description="Messages dropped because the send queue was full"
)
delivery_failures = meter.create_counter(
    "marketdata.delivery_failures", description="Messages the broker never acknowledged"
)


class MessagePublisher(Protocol):
    """Anything that can publish a message: the real Publisher, or a fake in tests."""

    def publish(self, topic: str, key: str | None, value: bytes) -> None: ...


class Publisher:
    def __init__(self, bootstrap_servers: str) -> None:
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "enable.idempotence": True,
                "linger.ms": 5,
                "compression.type": "zstd",
                "allow.auto.create.topics": False,
            }
        )

    def publish(self, topic: str, key: str | None, value: bytes) -> None:
        headers: dict[str, str] = {}
        inject(headers)
        try:
            self._producer.produce(
                topic,
                key=key,
                value=value,
                headers=list(headers.items()),
                on_delivery=self._on_delivery,
            )
        except BufferError:
            dropped.add(1, {"topic": topic})
            return
        published.add(1, {"topic": topic})
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        """Wait for queued messages to be delivered. Returns how many are still undelivered."""
        return self._producer.flush(timeout)

    @staticmethod
    def _on_delivery(err, msg) -> None:
        if err is not None:
            delivery_failures.add(1, {"topic": msg.topic()})
            logger.error("Delivery to %s failed: %s", msg.topic(), err)
