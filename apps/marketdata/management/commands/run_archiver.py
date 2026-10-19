import signal

from confluent_kafka import Consumer
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.marketdata.archive import Archive, LocalSegmentStore
from apps.marketdata.archiver import Archiver
from apps.marketdata.topics import KRAKEN_RAW
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Archive raw Kraken messages from Redpanda into compressed, offset-named segments."

    def handle(self, *args, **options):
        configure_telemetry(service_name="archiver")
        consumer = Consumer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id": "archiver",
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        store = LocalSegmentStore(settings.ARCHIVE_ROOT / "kraken" / "raw")
        archive = Archive(store, max_age_s=settings.ARCHIVE_SEGMENT_SECONDS)
        archiver = Archiver(consumer, KRAKEN_RAW.name, archive)
        signal.signal(signal.SIGINT, lambda *_: archiver.stop())
        signal.signal(signal.SIGTERM, lambda *_: archiver.stop())
        self.stdout.write(f"Archiving {KRAKEN_RAW.name} to {store.root}")
        archiver.run()
        self.stdout.write("Archiver stopped; open segments were published and committed")
