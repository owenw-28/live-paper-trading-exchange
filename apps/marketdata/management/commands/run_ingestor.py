import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.marketdata.ingestor import KrakenIngestor
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Stream Kraken order books and trades over one WebSocket, keeping verified books."

    def handle(self, *args, **options):
        configure_telemetry(service_name="ingestor")
        ingestor = KrakenIngestor(symbols=settings.MARKETDATA_SYMBOLS)
        try:
            asyncio.run(ingestor.run())
        except KeyboardInterrupt:
            self.stdout.write("Ingestor stopped")
