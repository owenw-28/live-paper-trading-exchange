import pytest
from django.db import transaction

from apps.core import outbox
from apps.core.models import OutboxEvent


@pytest.mark.django_db(transaction=True)
def test_outbox_refuses_writes_outside_a_transaction():
    with pytest.raises(RuntimeError, match="inside the change's transaction"):
        outbox.enqueue("orders.commands", "kraken:BTC/USD", "order.placed", {})

    assert not OutboxEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_outbox_event_rolls_back_with_its_change():
    with pytest.raises(RuntimeError, match="the change failed"), transaction.atomic():
        outbox.enqueue("orders.commands", "kraken:BTC/USD", "order.placed", {"order_id": 1})
        raise RuntimeError("the change failed")  # ...after the event was written

    assert not OutboxEvent.objects.exists()


@pytest.mark.django_db
def test_payload_carries_its_own_event_id():
    event = outbox.enqueue("orders.commands", "kraken:BTC/USD", "order.placed", {"order_id": 1})

    assert event.payload["event_id"] == str(event.id)
    assert event.payload["type"] == "order.placed"
    assert event.published_at is None
