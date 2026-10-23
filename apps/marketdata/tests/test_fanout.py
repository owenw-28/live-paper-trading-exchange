import asyncio
import json
from typing import cast

from channels.layers import InMemoryChannelLayer
from confluent_kafka import OFFSET_END, Consumer, Message, TopicPartition
from fakeredis import FakeAsyncRedis
from opentelemetry import trace
from opentelemetry.propagate import inject

from apps.marketdata.fanout import Fanout, _start_at_newest, _text_headers
from apps.marketdata.live import LiveState, group_name

BTC = "kraken:BTC/USD"


class FakeMessage:
    def __init__(self, topic: str, key: str | None, event: dict, headers=None) -> None:
        self._topic, self._key, self._headers = topic, key, headers
        self._value = json.dumps(event).encode()

    def error(self):
        return None

    def topic(self) -> str:
        return self._topic

    def key(self) -> bytes | None:
        return None if self._key is None else self._key.encode()

    def value(self) -> bytes:
        return self._value

    def headers(self):
        return self._headers


def book(n: int) -> FakeMessage:
    return FakeMessage("marketdata.book", BTC, {"symbol": "BTC/USD", "n": n, "ingested_at_ns": n})


def trade(n: int) -> FakeMessage:
    return FakeMessage(
        "marketdata.trades", BTC, {"symbol": "BTC/USD", "trade_id": n, "ingested_at_ns": n}
    )


async def deliver(messages) -> tuple[list[dict], LiveState]:
    layer = InMemoryChannelLayer()
    channel = await layer.new_channel()
    await layer.group_add(group_name(BTC), channel)
    live = LiveState(FakeAsyncRedis(decode_responses=True))
    fanout = Fanout(consumer=cast(Consumer, None), live=live, channel_layer=layer)
    await fanout.handle_batch(messages)  # handle_batch never touches the consumer
    received = []
    while True:
        try:
            received.append(await asyncio.wait_for(layer.receive(channel), timeout=0.05))
        except TimeoutError:
            return received, live


def test_group_name_has_no_slash():
    assert group_name(BTC) == "market.kraken.BTC-USD"


def test_batch_sends_every_trade_and_only_the_newest_book():
    received, _ = asyncio.run(deliver([book(1), trade(10), book(2), trade(11), book(3)]))

    kinds = [(m["type"], json.loads(m["frame"])["data"]) for m in received]
    assert [k for k, _ in kinds] == ["market.trade", "market.trade", "market.book"]
    assert [d.get("trade_id") for k, d in kinds if k == "market.trade"] == [10, 11]
    assert kinds[-1][1]["n"] == 3


def test_snapshot_holds_recent_trades_oldest_first_then_latest_book():
    async def scenario():
        _, live = await deliver([trade(10), trade(11), book(1), book(2)])
        return [json.loads(text) for text in await live.snapshot(BTC)]

    snapshot = asyncio.run(scenario())

    assert [f["type"] for f in snapshot] == ["trade", "trade", "book"]
    assert [f["data"].get("trade_id") for f in snapshot[:2]] == [10, 11]
    assert snapshot[-1]["data"]["n"] == 2


def test_fanout_continues_the_ingestors_trace(finished_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("kraken book") as producer_span:
        carrier: dict[str, str] = {}
        inject(carrier)
    headers = [(key, value.encode()) for key, value in carrier.items()]
    message = FakeMessage("marketdata.book", BTC, {"ingested_at_ns": 1}, headers)

    asyncio.run(deliver([message]))

    fanout_span = next(s for s in finished_spans.get_finished_spans() if s.name == "fanout book")
    assert fanout_span.context.trace_id == producer_span.get_span_context().trace_id
    assert fanout_span.parent.span_id == producer_span.get_span_context().span_id


def test_assigned_partitions_start_at_the_newest_message():
    class FakeConsumer:
        def assign(self, partitions):
            self.assigned = partitions

    consumer = FakeConsumer()
    _start_at_newest(cast(Consumer, consumer), [TopicPartition("marketdata.book", 4, 1234)])

    assert [(tp.partition, tp.offset) for tp in consumer.assigned] == [(4, OFFSET_END)]


def test_fanout_records_ingest_to_broadcast_latency(histogram_counts):
    asyncio.run(deliver([book(1), book(2), trade(10)]))

    assert histogram_counts("marketdata.ingest_to_broadcast") == {
        (("kind", "book"),): 1,
        (("kind", "trade"),): 1,
    }


def test_message_without_key_is_skipped_not_fatal():
    keyless = FakeMessage("marketdata.book", None, {"ingested_at_ns": 1})

    received, _ = asyncio.run(deliver([keyless, book(1)]))

    assert [json.loads(m["frame"])["data"]["n"] for m in received] == [1]


def test_headers_are_read_as_text_in_either_kafka_shape():
    as_list = FakeMessage("t", BTC, {}, [("traceparent", b"00-abc"), ("empty", None)])
    as_dict = FakeMessage("t", BTC, {}, {"traceparent": "00-abc"})

    assert _text_headers(cast(Message, as_list)) == {"traceparent": "00-abc"}
    assert _text_headers(cast(Message, as_dict)) == {"traceparent": "00-abc"}
