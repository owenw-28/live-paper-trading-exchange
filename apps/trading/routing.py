from typing import Any

from django.urls import path

from apps.trading.consumers import UserConsumer

websocket_urlpatterns: list[Any] = [
    path("ws/user/", UserConsumer.as_asgi()),  # type: ignore[arg-type]
]
