from typing import Any

from django.conf import settings
from django.urls import path

from apps.marketdata.consumers import MarketDataConsumer
from apps.marketdata.live import LiveState

websocket_urlpatterns: list[Any] = [
    path(
        "ws/market/",
        MarketDataConsumer.as_asgi(live=LiveState.from_url(settings.REDIS_URL)),  # type: ignore[arg-type]
    ),
]
