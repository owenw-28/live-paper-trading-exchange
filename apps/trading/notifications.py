"""Pushing a user's order changes to their open browser tabs.

Best effort: the database is the truth. If a push is lost (no tab open, Redis hiccup), the
browser catches up from the REST API when it next fetches or reconnects.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from opentelemetry import metrics

from apps.trading.models import Order
from apps.trading.serializers import OrderSerializer

logger = logging.getLogger(__name__)
push_failures = metrics.get_meter(__name__).create_counter(
    "user.push_failures", description="Order updates that couldn't be pushed to browsers"
)


def user_group(user_id: int) -> str:
    return f"user.{user_id}"


def notify_user(order: Order) -> None:
    """Send the order, as the REST API shows it, to every socket its owner has open."""
    layer = get_channel_layer()
    assert layer is not None
    message = {"type": "user.order", "order": dict(OrderSerializer(order).data)}
    try:
        async_to_sync(layer.group_send)(user_group(order.user_id), message)
    except Exception:
        logger.exception("Couldn't push order %s to user %s", order.id, order.user_id)
        push_failures.add(1)
