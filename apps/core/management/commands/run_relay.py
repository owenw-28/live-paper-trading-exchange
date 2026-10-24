import signal
import time

import psycopg
from confluent_kafka import Producer
from django.conf import settings
from django.core.management.base import BaseCommand
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from apps.core import outbox, relay
from config.telemetry import configure_telemetry


class Command(BaseCommand):
    help = "Publish committed outbox events to Redpanda. Run several; only one is active."

    def handle(self, *args, **options):
        configure_telemetry(service_name="relay")
        self.stopping = False
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)
        meter = metrics.get_meter(__name__)
        meter.create_observable_gauge(
            "outbox.backlog",
            callbacks=[lambda options: [Observation(relay.backlog())]],
            description="Outbox events not yet published",
        )
        meter.create_observable_gauge(
            "outbox.oldest_unpublished_age",
            unit="s",
            callbacks=[self._observe_age],
            description="Age of the oldest unpublished outbox event",
        )
        producer = Producer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "enable.idempotence": True,
                "linger.ms": 0,  # orders are latency-sensitive: send at once
                "allow.auto.create.topics": False,
            }
        )
        publisher = relay.Relay(producer)
        # A dedicated connection, outside Django's pool: it holds the leader lock and listens for
        # NOTIFY. If this process dies, the connection drops and Postgres frees the lock.
        with psycopg.connect(**_conninfo(), autocommit=True) as listener:
            self._wait_for_leadership(listener)
            if self.stopping:
                return
            listener.execute(f"LISTEN {outbox.CHANNEL}")
            self.stdout.write("Leader: publishing outbox events")
            while not self.stopping:
                if publisher.publish_pending() == publisher.batch_size:
                    continue  # more waiting: go straight round again
                for _ in listener.notifies(timeout=1.0, stop_after=1):
                    pass  # woken by a commit, or after 1 s as a safety net
        producer.flush(10)
        self.stdout.write("Relay stopped")

    def _wait_for_leadership(self, listener: psycopg.Connection) -> None:
        while not self.stopping:
            row = listener.execute(
                "SELECT pg_try_advisory_lock(%s)", (relay.LEADER_LOCK_ID,)
            ).fetchone()
            if row is not None and row[0]:
                return
            self.stdout.write("Standby: another relay is active")
            time.sleep(2)

    def _stop(self, *args) -> None:
        self.stopping = True

    def _observe_age(self, options: CallbackOptions):
        yield Observation(relay.oldest_unpublished_age_s())


def _conninfo() -> dict:
    db = settings.DATABASES["default"]
    return {
        "dbname": db["NAME"],
        "user": db["USER"],
        "password": db["PASSWORD"],
        "host": db["HOST"],
        "port": db["PORT"],
    }
