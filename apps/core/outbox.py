"""The write side of the transactional outbox."""

from django.db import connection
from django.utils import timezone
from opentelemetry.propagate import inject

from apps.core.models import OutboxEvent

SCHEMA_VERSION = 1
CHANNEL = "outbox"


def enqueue(topic: str, key: str, event_type: str, data: dict) -> OutboxEvent:
    """Record an event to publish. Must run inside the transaction that makes the change."""
    if not connection.in_atomic_block:
        raise RuntimeError("outbox events must be written inside the change's transaction")
    event = OutboxEvent(topic=topic, key=key)
    event.payload = {
        "v": SCHEMA_VERSION,
        "event_id": str(event.id),
        "type": event_type,
        "occurred_at": timezone.now().isoformat(),
        "data": data,
    }
    inject(event.headers)
    event.save()
    with connection.cursor() as cursor:
        cursor.execute(f"NOTIFY {CHANNEL}")
    return event
