import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.lifecycle import run_until_stopped
from apps.marketdata.ingestor import KrakenIngestor
from apps.marketdata.publisher import Publisher
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Stream Kraken order books and trades over one WebSocket and publish them to Redpanda."

    def handle(self, *args, **options):
        configure_telemetry(service_name="ingestor")
        publisher = Publisher(settings.KAFKA_BOOTSTRAP_SERVERS)
        ingestor = KrakenIngestor(
            symbols=settings.MARKETDATA_SYMBOLS,
            publisher=publisher,
            depth=settings.MARKETDATA_BOOK_DEPTH,
        )
        try:
            asyncio.run(run_until_stopped(ingestor.run()))
        finally:
            undelivered = publisher.flush()
            self.stdout.write(f"Ingestor stopped; {undelivered} messages undelivered after flush")
