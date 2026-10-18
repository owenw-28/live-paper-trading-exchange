from confluent_kafka.admin import AdminClient, NewTopic
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.marketdata.topics import ALL_TOPICS


class Command(BaseCommand):
    help = "Create the market data topics in Redpanda if they don't already exist."

    def handle(self, *args, **options):
        admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        existing = admin.list_topics(timeout=10).topics
        missing = [
            NewTopic(
                topic.name,
                num_partitions=topic.partitions,
                replication_factor=settings.KAFKA_REPLICATION_FACTOR,
                config={"retention.ms": str(topic.retention_ms)},
            )
            for topic in ALL_TOPICS
            if topic.name not in existing
        ]
        if not missing:
            self.stdout.write("All topics already exist")
            return
        for name, future in admin.create_topics(missing).items():
            future.result()
            self.stdout.write(f"Created {name}")
