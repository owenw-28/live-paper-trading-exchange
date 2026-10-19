import asyncio
import signal

from channels.layers import get_channel_layer
from confluent_kafka import Consumer
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.marketdata.fanout import Fanout
from apps.marketdata.live import LiveState
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Fan verified books and trades out from Redpanda to Redis and WebSocket clients."

    def handle(self, *args, **options):
        configure_telemetry(service_name="fanout")
        consumer = Consumer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id": "fanout",
                "enable.auto.commit": True,
                "auto.offset.reset": "latest",
            }
        )
        fanout = Fanout(consumer, LiveState.from_url(settings.REDIS_URL), get_channel_layer())
        self.stdout.write("Fanning out market data to Redis and WebSocket groups")
        asyncio.run(self._run(fanout))
        self.stdout.write("Fan-out stopped")

    async def _run(self, fanout: Fanout) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, fanout.stop)
        await fanout.run()
