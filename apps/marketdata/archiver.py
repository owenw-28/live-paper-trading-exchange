"""Consumes raw venue messages from Redpanda and writes them to the archive."""

import logging

from confluent_kafka import Consumer, KafkaException, TopicPartition
from opentelemetry import metrics

from apps.marketdata.archive import Archive, Segment

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)

archived_messages = meter.creater_counter(
    "archive.messages", description="Messages written into published segments"
)
archived_segments = meter.create_counter("archive.segments", description="Segments published")
archived_bytes = meter.create_counter(
    "archive.bytes", unit="By", description="Bytes archived, before and after compression"
)


class Archiver:
    def __init__(self, consumer: Consumer, topic: str, archive: Archive) -> None:
        self.consumer = consumer
        self.topic = topic
        self.archive = archive
        self._stopping = False

    def run(self) -> None:
        self.archive.store.discard_temporary()
        self.consumer.subscribe(
            [self.topic],
            on_assign=self._on_assign,
            on_revoke=self._on_revoke,
            on_lost=self._on_revoke,
        )
        while not self._stopping:
            for message in self.consumer.consume(num_messages=500, timeout=1.0):
                if message.error():
                    logger.error("Consumer error: %s", message.error())
                    continue
                _, timestamp_ms = message.timestamp()
                segment = self.archive.append(
                    message.partition(), message.offset(), timestamp_ms, message.value()
                )
                if segment is not None:
                    self._committed(segment)
            for segment in self.archive.finish_due():
                self._committed(segment)
        for segment in self.archive.finish_all():
            self._committed(segment)
        self.consumer.close()

    def stop(self) -> None:
        self._stopping = True

    def _committed(self, segment: Segment) -> None:
        archived_messages.add(segment.messages, {"partition": segment.partition})
        archived_segments.add(1, {"partition": segment.partition})
        archived_bytes.add(segment.raw_bytes, {"kind": "raw"})
        archived_bytes.add(segment.path.stat().st_size, {"kind": "compressed"})
        next_offset = TopicPartition(self.topic, segment.partition, segment.last_offset + 1)
        try:
            self.consumer.commit(offsets=[next_offset], asynchronous=False)
        except KafkaException as exc:
            logger.warning("Commit failed after archiving %s: %s", segment.path.name, exc)

    def _on_assign(self, consumer: Consumer, partitions: list[TopicPartition]) -> None:
        for tp in partitions:
            resume = self.archive.resume_offset(tp.partition)
            if resume is not None:
                tp.offset = resume
        logger.info("Assigned partitions %s", [(tp.partition, tp.offset) for tp in partitions])
        consumer.assign(partitions)

    def _on_revoke(self, consumer: Consumer, partitions: list[TopicPartition]) -> None:
        for tp in partitions:
            self.archive.abandon(tp.partition)
        logger.info("Revoked partitions %s", [tp.partition for tp in partitions])
        