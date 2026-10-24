import signal

from confluent_kafka import Consumer
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.trading.settlement_service import SettlementService
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Apply fill engine outcomes to orders and the ledger."

    def handle(self, *args, **options):
        configure_telemetry(service_name="settlement")
        self.stopping = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)
        consumer = Consumer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id": "settlement",
                "session.timeout.ms": 10000,  # a dead member's partitions move on within 10 s
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",  # never skip an outcome
            }
        )
        service = SettlementService(consumer)
        service.start()
        self.stdout.write("Settling orders")
        try:
            while not self.stopping:
                service.step()
        finally:
            consumer.close()
        self.stdout.write("Settlement stopped")

    def _stop(self, *args) -> None:
        self.stopping = True
