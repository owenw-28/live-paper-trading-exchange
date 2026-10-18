import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.marketdata.ingestor import KrakenIngestor
from apps.marketdata.publisher import Publisher
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Stream Kraken order books and trades over one WebSocket and publish them to Redpanda."

    def handle(self, *args, **options):
        configure_telemetry(service_name="ingestor")
        publisher = Publisher(settings.KAFKA_BOOTSTRAP_SERVERS)
        ingestor = KrakenIngestor(symbols=settings.MARKETDATA_SYMBOLS, publisher=publisher)
        try:
            asyncio.run(ingestor.run())
        except KeyboardInterrupt:
            self.stdout.write("Ingestor stopping")
        finally:
            undelivered = publisher.flush()
            self.stdout.write(f"Flushed publisher; {undelivered} messages undelivered")
