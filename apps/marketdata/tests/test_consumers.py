import asyncio
import json
from typing import Any

import pytest
from channels.layers import BaseChannelLayer, get_channel_layer
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.testing import WebsocketCommunicator
from django.urls import path
from fakeredis import FakeAsyncRedis

from apps.marketdata.consumers import MarketDataConsumer
from apps.marketdata.live import LiveState, frame, group_name

BTC = "kraken:BTC/USD"
ORIGIN = [(b"origin", b"http://localhost:5173")]


@pytest.fixture(autouse=True)
def in_memory_channel_layer(settings):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    settings.MARKETDATA_SYMBOLS = ["BTC/USD", "ETH/USD"]
    settings.MARKETDATA_MAX_BOOKS_PER_SECOND = 10
    settings.ALLOWED_HOSTS = ["localhost"]


def app(live: LiveState) -> URLRouter:
    routes: list[Any] = [path("ws/market/", MarketDataConsumer.as_asgi(live=live))]  # type: ignore[arg-type]
    return URLRouter(routes)


def layer() -> BaseChannelLayer:
    channel_layer = get_channel_layer()
    assert channel_layer is not None
    return channel_layer


def book_message(n: int) -> dict:
    event = {"symbol": "BTC/USD", "n": n, "ingested_at_ns": 0}
    return {
        "type": "market.book",
        "instrument": BTC,
        "frame": frame("book", event),
        "ingested_at_ns": 0,
    }


async def receive_json(communicator, timeout=1.0) -> dict:
    return json.loads(await communicator.receive_from(timeout=timeout))


def test_client_gets_snapshot_then_live_updates():
    async def scenario():
        live = LiveState(FakeAsyncRedis(decode_responses=True))
        await live.save_book(BTC, frame("book", {"n": 0}))
        communicator = WebsocketCommunicator(app(live), "/ws/market/?symbols=BTC/USD")
        connected, _ = await communicator.connect()
        snapshot = await receive_json(communicator)
        await layer().group_send(group_name(BTC), book_message(1))
        update = await receive_json(communicator)
        await communicator.disconnect()
        return connected, snapshot, update

    connected, snapshot, update = asyncio.run(scenario())

    assert connected
    assert snapshot == {"type": "book", "data": {"n": 0}}
    assert update["data"]["n"] == 1


def test_burst_of_books_is_conflated_to_the_newest():
    async def scenario():
        live = LiveState(FakeAsyncRedis(decode_responses=True))
        communicator = WebsocketCommunicator(app(live), "/ws/market/?symbols=BTC/USD")
        await communicator.connect()
        for n in range(50):
            await layer().group_send(group_name(BTC), book_message(n))
        received: list[int] = []
        while not received or received[-1] != 49:
            received.append((await receive_json(communicator))["data"]["n"])
        await communicator.disconnect()
        return received

    received = asyncio.run(scenario())

    assert received[-1] == 49
    assert len(received) < 50


def test_unsupported_symbol_is_rejected():
    async def scenario():
        live = LiveState(FakeAsyncRedis(decode_responses=True))
        communicator = WebsocketCommunicator(app(live), "/ws/market/?symbols=DOGE/USD")
        connected, _ = await communicator.connect()
        return connected

    assert asyncio.run(scenario()) is False


def test_foreign_origin_is_rejected():
    async def scenario():
        live = LiveState(FakeAsyncRedis(decode_responses=True))
        guarded = AllowedHostsOriginValidator(app(live))
        evil = WebsocketCommunicator(
            guarded, "/ws/market/", headers=[(b"origin", b"http://evil.example")]
        )
        ok = WebsocketCommunicator(guarded, "/ws/market/", headers=ORIGIN)
        evil_connected, _ = await evil.connect()
        ok_connected, _ = await ok.connect()
        await ok.disconnect()
        return evil_connected, ok_connected

    assert asyncio.run(scenario()) == (False, True)
