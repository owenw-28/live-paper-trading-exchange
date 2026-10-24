import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import cast

import pytest
from confluent_kafka import OFFSET_END, Consumer, TopicPartition
from django.contrib.auth.models import User

from apps.trading.engine import EngineOrder, FillEngine
from apps.trading.engine_service import EngineFailure, EngineService, unfinished_orders
from apps.trading.models import Order, OrderStatus

FEE = Decimal("0.0025")


class FakeMessage:
    def __init__(self, topic: str, value: dict, offset: int = 0, headers=None) -> None:
        self._topic, self._value, self._offset, self._headers = topic, value, offset, headers

    def error(self):
        return None

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes:
        return json.dumps(self._value).encode()

    def headers(self):
        return self._headers


class FakeConsumer:
    def __init__(self, assign_on_subscribe: bool = True) -> None:
        self.assign_on_subscribe = assign_on_subscribe
        self.topics: list[str] = []
        self.on_assign: Callable[..., None] = lambda consumer, partitions: None
        self.queue: list[FakeMessage] = []
        self.assigned: list[TopicPartition] = []
        self.paused: list[str] = []
        self.commits: list[tuple[str, int, int]] = []

    def subscribe(self, topics, on_assign) -> None:
        self.topics, self.on_assign = topics, on_assign
        if self.assign_on_subscribe:
            self.rebalance()

    def rebalance(self) -> None:
        self.on_assign(self, [TopicPartition(topic, 0) for topic in self.topics])

    def assign(self, partitions) -> None:
        self.assigned = partitions

    def pause(self, partitions) -> None:
        self.paused = [tp.topic for tp in partitions]

    def resume(self, partitions) -> None:
        self.paused = []

    def poll(self, timeout):
        return self.queue.pop(0) if self.queue else None

    def consume(self, num_messages, timeout):
        batch, self.queue = self.queue, []
        return batch

    def commit(self, offsets, asynchronous) -> None:
        self.commits += [(tp.topic, tp.partition, tp.offset) for tp in offsets]


class FakeProducer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []

    def produce(self, topic, *, key, value, headers, on_delivery) -> None:
        self.sent.append(
            {"topic": topic, "key": key, "value": json.loads(value), "headers": dict(headers)}
        )
        on_delivery("broker down" if self.fail else None, None)

    def flush(self, timeout) -> int:
        return 0


def book() -> FakeMessage:
    levels = [["100.0", "5"]]
    event = {
        "symbol": "BTC/USD",
        "bids": [["99.9", "5"]],
        "asks": levels,
        "ingested_at_ns": time.time_ns(),
    }
    return FakeMessage("marketdata.book", event)


def placed(order_id: int, offset: int, order_type: str = "market", limit: str | None = None):
    data = {
        "order_id": order_id,
        "user_id": 1,
        "symbol": "BTC/USD",
        "side": "buy",
        "type": order_type,
        "quantity": "1",
        "limit_price": limit,
        "reserved_amount": "1000",
    }
    command = {"type": "order.placed", "occurred_at": "2026-10-24T12:00:00+00:00", "data": data}
    return FakeMessage("orders.commands", command, offset)


def service(producer=None, unfinished=([], set()), consumer=None):
    consumer = consumer or FakeConsumer()
    svc = EngineService(
        cast(Consumer, consumer),
        producer or FakeProducer(),
        FillEngine(FEE),
        ["BTC/USD"],
        lambda: unfinished,
    )
    svc.start()
    return svc, consumer


def test_market_data_starts_at_the_newest_message_and_commands_where_we_left_off():
    _, consumer = service()

    offsets = {tp.topic: tp.offset for tp in consumer.assigned}
    assert offsets["marketdata.book"] == offsets["marketdata.trades"] == OFFSET_END
    assert offsets["orders.commands"] != OFFSET_END


def test_commands_wait_until_there_are_live_prices():
    svc, consumer = service()
    assert consumer.paused == ["orders.commands"]

    consumer.queue.append(book())
    svc.step()

    assert svc.recovered
    assert consumer.paused == []


def test_no_recovery_before_partitions_are_assigned(monkeypatch):
    # After a crash, the dead leader's group membership blocks assignment until it times out.
    monkeypatch.setattr("apps.trading.engine_service.WARM_UP_TIMEOUT_S", 0)
    svc, consumer = service(consumer=FakeConsumer(assign_on_subscribe=False))

    svc.step()
    assert not svc.recovered

    consumer.rebalance()
    svc.step()
    assert svc.recovered


def test_outcome_is_published_before_the_command_offset_is_committed():
    producer = FakeProducer()
    svc, consumer = service(producer)
    consumer.queue += [book(), placed(order_id=7, offset=41)]

    svc.step()

    [sent] = producer.sent
    assert (sent["topic"], sent["key"]) == ("orders.events", "kraken:BTC/USD")
    assert sent["headers"]["event_id"] == "order.filled:7"
    assert sent["value"]["data"]["quote_amount"] == "100.00"
    assert consumer.commits == [("orders.commands", 0, 42)]


def test_unacknowledged_outcomes_stop_the_engine_without_committing():
    svc, consumer = service(FakeProducer(fail=True))
    consumer.queue += [book(), placed(order_id=7, offset=41)]

    with pytest.raises(EngineFailure):
        svc.step()

    assert consumer.commits == []


def test_recovery_decides_unfinished_orders_from_the_database():
    resting = EngineOrder(
        1, 1, "BTC/USD", "buy", "limit", Decimal("1"), Decimal("90.0"), Decimal("100")
    )
    producer = FakeProducer()
    svc, consumer = service(producer, unfinished=([resting], set()))
    consumer.queue.append(book())

    svc.step()

    assert [m["headers"]["event_id"] for m in producer.sent] == ["order.accepted:1"]
    consumer.queue.append(FakeMessage("marketdata.trades", {"symbol": "BTC/USD", "price": "89.9"}))
    svc.step()
    assert producer.sent[-1]["headers"]["event_id"] == "order.filled:1"


@pytest.mark.django_db
def test_unfinished_orders_are_pending_or_open_with_cancels_marked():
    user = User.objects.create(username="owen")
    common = {
        "user": user,
        "symbol": "BTC/USD",
        "side": "buy",
        "order_type": "limit",
        "quantity": 1,
        "limit_price": 90,
        "reserved_asset": "USD",
        "reserved_amount": 91,
    }
    pending = Order.objects.create(idempotency_key="k1", **common)
    cancelling = Order.objects.create(
        idempotency_key="k2", status=OrderStatus.OPEN, cancel_requested=True, **common
    )
    Order.objects.create(idempotency_key="k3", status=OrderStatus.FILLED, **common)

    orders, cancels = unfinished_orders()

    assert [o.order_id for o in orders] == [pending.id, cancelling.id]
    assert cancels == {cancelling.id}
