from django.conf import settings
from django.urls import path

from apps.marketdata.consumers import MarketDataConsumer
from apps.marketdata.live import LiveState

websocket_urlpatterns = [
    path("ws/market/", MarketDataConsumer.as_asgi(live=LiveState.from_url(settings.REDIS_URL))),
]
