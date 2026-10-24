"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/

HTTP requests go to Django; WebSocket connections go to Channels consumers.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.telemetry import configure_telemetry  # noqa: E402

configure_telemetry(service_name="web")

django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.marketdata.routing import websocket_urlpatterns as market_routes  # noqa: E402
from apps.trading.routing import websocket_urlpatterns as user_routes  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(market_routes + user_routes))
        ),
    }
)
