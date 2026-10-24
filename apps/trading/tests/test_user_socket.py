import asyncio
import uuid
from decimal import Decimal

import pytest
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client

from apps.ledger import services as ledger
from apps.trading.models import Order
from apps.trading.notifications import notify_user
from apps.trading.routing import websocket_urlpatterns
from apps.trading.services import OrderRequest, place_order

# Sockets run their database work in other threads, which only see committed data.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def in_memory_channel_layer(settings):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


def app():
    return AuthMiddlewareStack(URLRouter(websocket_urlpatterns))


def session_cookie(user: User) -> list[tuple[bytes, bytes]]:
    client = Client()
    client.force_login(user)
    session_id = client.cookies[django_settings.SESSION_COOKIE_NAME].value
    return [(b"cookie", f"{django_settings.SESSION_COOKIE_NAME}={session_id}".encode())]


def order_for(name: str) -> tuple[User, int]:
    user = User.objects.create(username=name)
    ledger.fund_new_user(user)
    request = OrderRequest("BTC/USD", "buy", "limit", Decimal("0.01"), Decimal("1000.0"))
    order, _ = place_order(user, request, uuid.uuid4().hex)
    return user, order.id


def test_anonymous_connections_are_refused():
    async def scenario():
        communicator = WebsocketCommunicator(app(), "/ws/user/")
        connected, _ = await communicator.connect()
        return connected

    assert not asyncio.run(scenario())


def test_users_receive_their_own_order_updates_and_nobody_elses():
    owen, owens_order = order_for("owen")
    _, other_order = order_for("mallory")
    cookie = session_cookie(owen)

    async def scenario():
        communicator = WebsocketCommunicator(app(), "/ws/user/", headers=cookie)
        connected, _ = await communicator.connect()
        push = database_sync_to_async(lambda order_id: notify_user(Order.objects.get(id=order_id)))
        await push(other_order)
        await push(owens_order)
        received = await communicator.receive_json_from(timeout=1)
        nothing_else = await communicator.receive_nothing(timeout=0.2)
        await communicator.disconnect()
        return connected, received, nothing_else

    connected, received, nothing_else = asyncio.run(scenario())

    assert connected
    assert received["type"] == "order"
    assert received["order"]["id"] == owens_order
    assert received["order"]["status"] == "pending"
    assert received["order"]["limit_price"] == "1000.00000000"  # same shape as the REST API
    assert nothing_else
