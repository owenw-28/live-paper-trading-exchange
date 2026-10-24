import json

import psycopg
import pytest
from django.db import connection, transaction
from opentelemetry import trace

from apps.core import outbox
from apps.core.models import OutboxEvent
from apps.core.relay import LEADER_LOCK_ID, Relay


class FakeProducer:
    """Records messages; on flush, acknowledges each one unless its event id is in `fail`."""

    def __init__(self, fail: frozenset[str] = frozenset()) -> None:
        self.fail = fail
        self.sent: list[dict] = []
        self._pending: list = []

    def produce(self, topic, *, key, value, headers, on_delivery) -> None:
        message = {"topic": topic, "key": key, "value": json.loads(value), "headers": dict(headers)}
        self.sent.append(message)
        self._pending.append((message, on_delivery))

    def flush(self, timeout: float) -> int:
        failed = 0
        for message, on_delivery in self._pending:
            if message["headers"]["event_id"] in self.fail:
                on_delivery("broker unavailable", None)
                failed += 1
            else:
                on_delivery(None, None)
        self._pending = []
        return failed


def enqueue(n: int) -> OutboxEvent:
    with transaction.atomic():
        return outbox.enqueue("orders.commands", "kraken:BTC/USD", "order.placed", {"n": n})


@pytest.mark.django_db
def test_publishes_oldest_first_and_marks_them_published():
    events = [enqueue(n) for n in range(3)]
    producer = FakeProducer()

    published = Relay(producer).publish_pending()

    assert published == 3
    assert [m["value"]["data"]["n"] for m in producer.sent] == [0, 1, 2]
    first = producer.sent[0]
    assert (first["topic"], first["key"]) == ("orders.commands", "kraken:BTC/USD")
    assert first["headers"]["event_id"] == str(events[0].id)
    assert not OutboxEvent.objects.filter(published_at__isnull=True).exists()
    assert Relay(producer).publish_pending() == 0  # nothing left to do


@pytest.mark.django_db
def test_unacknowledged_events_stay_pending_and_are_retried():
    ok, lost = enqueue(1), enqueue(2)

    Relay(FakeProducer(fail=frozenset({str(lost.id)}))).publish_pending()

    assert OutboxEvent.objects.get(id=ok.id).published_at is not None
    assert OutboxEvent.objects.get(id=lost.id).published_at is None
    retry = FakeProducer()
    assert Relay(retry).publish_pending() == 1
    assert retry.sent[0]["headers"]["event_id"] == str(lost.id)


@pytest.mark.django_db
def test_a_crash_before_marking_republishes_with_the_same_event_id():
    event = enqueue(1)
    first = FakeProducer()
    Relay(first).publish_pending()
    OutboxEvent.objects.filter(id=event.id).update(published_at=None)  # "crashed" before marking

    second = FakeProducer()
    Relay(second).publish_pending()

    assert first.sent[0]["headers"]["event_id"] == second.sent[0]["headers"]["event_id"]


@pytest.mark.django_db
def test_the_trace_continues_from_the_request_through_the_relay(finished_spans):
    with trace.get_tracer("test").start_as_current_span("POST /api/orders") as request_span:
        enqueue(1)
    producer = FakeProducer()

    Relay(producer).publish_pending()

    relay_span = next(s for s in finished_spans.get_finished_spans() if s.name.startswith("outbox"))
    assert relay_span.parent.span_id == request_span.get_span_context().span_id
    trace_id = f"{request_span.get_span_context().trace_id:032x}"
    assert trace_id in producer.sent[0]["headers"]["traceparent"]


def listener() -> psycopg.Connection:
    db = connection.settings_dict
    return psycopg.connect(
        dbname=db["NAME"],
        user=db["USER"],
        password=db["PASSWORD"],
        host=db["HOST"],
        port=db["PORT"],
        autocommit=True,
    )


@pytest.mark.django_db(transaction=True)
def test_relay_is_woken_only_when_the_event_commits():
    with listener() as conn:
        conn.execute(f"LISTEN {outbox.CHANNEL}")
        with transaction.atomic():
            outbox.enqueue("orders.commands", "kraken:BTC/USD", "order.placed", {})
            before_commit = list(conn.notifies(timeout=0.2, stop_after=1))
        after_commit = list(conn.notifies(timeout=2, stop_after=1))

    assert before_commit == []
    assert [n.channel for n in after_commit] == [outbox.CHANNEL]


@pytest.mark.django_db(transaction=True)
def test_only_one_relay_holds_the_leader_lock_at_a_time():
    take = "SELECT pg_try_advisory_lock(%s)"
    with listener() as first, listener() as second:
        assert first.execute(take, (LEADER_LOCK_ID,)).fetchone() == (True,)
        assert second.execute(take, (LEADER_LOCK_ID,)).fetchone() == (False,)
        first.close()  # the leader dies: Postgres frees its lock with its connection
        assert second.execute(take, (LEADER_LOCK_ID,)).fetchone() == (True,)
