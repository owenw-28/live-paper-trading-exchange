import json
from types import SimpleNamespace
from typing import cast

import pytest
from confluent_kafka import Consumer, TopicPartition

from apps.trading import settlement_service
from apps.trading.settlement_service import SettlementService


class FakeMessage:
    def __init__(self, offset: int, partition: int = 0) -> None:
        self._offset, self._partition = offset, partition

    def error(self):
        return None

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes:
        event = {"event_id": f"order.accepted:{self._offset}", "type": "order.accepted"}
        return json.dumps({**event, "data": {"order_id": self._offset}}).encode()

    def headers(self):
        return None


class FakeConsumer:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self.queue = messages
        self.commits: list[tuple[int, int]] = []

    def subscribe(self, topics) -> None:
        self.topics = topics

    def poll(self, timeout):
        return self.queue.pop(0) if self.queue else None

    def consume(self, num_messages, timeout):
        batch, self.queue = self.queue, []
        return batch

    def commit(self, offsets: list[TopicPartition], asynchronous) -> None:
        self.commits += [(tp.partition, tp.offset) for tp in offsets]


def service(messages):
    consumer = FakeConsumer(messages)
    pushed: list = []
    svc = SettlementService(cast(Consumer, consumer), notify=pushed.append)
    svc.start()
    return svc, consumer, pushed


def test_offsets_are_committed_after_the_batch_is_settled(monkeypatch):
    settled: list[int] = []
    monkeypatch.setattr(
        settlement_service, "settle", lambda event: settled.append(event["data"]["order_id"])
    )
    svc, consumer, _ = service([FakeMessage(5), FakeMessage(9, partition=2), FakeMessage(6)])

    assert svc.step() == 3

    assert settled == [5, 9, 6]
    assert sorted(consumer.commits) == [(0, 7), (2, 10)]  # the next offset to read


def test_a_database_failure_commits_nothing(monkeypatch):
    def broken(event):
        raise RuntimeError("database down")

    monkeypatch.setattr(settlement_service, "settle", broken)
    svc, consumer, _ = service([FakeMessage(5)])

    with pytest.raises(RuntimeError):
        svc.step()

    assert consumer.commits == []


def test_only_applied_outcomes_are_pushed_to_the_user(monkeypatch):
    applied = SimpleNamespace(id=5, settled_at=None)
    monkeypatch.setattr(
        settlement_service,
        "settle",
        lambda event: applied if event["data"]["order_id"] == 5 else None,
    )
    svc, _, pushed = service([FakeMessage(5), FakeMessage(6)])

    svc.step()

    assert pushed == [applied]  # order 6 was a repeat: nothing changed, nothing to tell
