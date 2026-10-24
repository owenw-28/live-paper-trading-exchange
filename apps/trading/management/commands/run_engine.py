import signal

from confluent_kafka import Consumer, Producer
from django.conf import settings
from django.core.management.base import BaseCommand
from opentelemetry import metrics
from opentelemetry.metrics import Observation

from apps.core.leadership import dedicated_connection, wait_to_lead
from apps.trading.engine import FillEngine
from apps.trading.engine_service import LEADER_LOCK_ID, EngineService
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Fill paper orders against the live Kraken book. Run several; only one is active."

    def handle(self, *args, **options):
        configure_telemetry(service_name="engine")
        self.stopping = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)
        engine = FillEngine(settings.TRADING_FEE_RATE)
        metrics.get_meter(__name__).create_observable_gauge(
            "engine.resting_orders",
            callbacks=[lambda options: [Observation(engine.resting_count())]],
            description="Limit orders waiting for the market to trade through their price",
        )
        consumer = Consumer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id": "fill-engine",
                "session.timeout.ms": 10000,  # a killed leader's partitions move on within 10 s
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        producer = Producer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "enable.idempotence": True,
                "linger.ms": 0,
                "allow.auto.create.topics": False,
            }
        )
        service = EngineService(consumer, producer, engine, settings.MARKETDATA_SYMBOLS)
        with dedicated_connection() as lock:
            if not wait_to_lead(lock, LEADER_LOCK_ID, self._is_stopping, self._standby):
                return
            self.stdout.write("Leader: filling orders")
            service.start()
            try:
                while not self.stopping:
                    service.step()
            finally:
                consumer.close()
        self.stdout.write("Engine stopped")

    def _stop(self, *args) -> None:
        self.stopping = True

    def _is_stopping(self) -> bool:
        return self.stopping

    def _standby(self) -> None:
        self.stdout.write("Standby: another engine is active")
