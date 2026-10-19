from confluent_kafka import TopicPartition

from apps.marketdata.archive import Archive, LocalSegmentStore, read_segment, segment_range
from apps.marketdata.archiver import Archiver

TS = 1_792_022_400_000  # 2026-10-15T00:00:00Z in milliseconds


def write(archive: Archive, partition: int, offsets: range) -> None:
    for offset in offsets:
        archive.append(partition, offset, TS + offset, f'{{"n":{offset}}}'.encode())


def test_finished_segment_is_named_by_offset_range_and_round_trips(tmp_path):
    archive = Archive(LocalSegmentStore(tmp_path))
    write(archive, 5, range(100, 103))

    segment = archive.finish(5)

    assert segment.path.name == "offsets-000000000100-000000000102.jsonl.zst"
    assert segment.path.parent.name == "2026-10-15"
    assert segment_range(segment.path) == (100, 102)
    records = list(read_segment(segment.path))
    assert [r["offset"] for r in records] == [100, 101, 102]
    assert records[0]["raw"] == '{"n":100}'


def test_resume_offset_is_after_highest_archived_offset(tmp_path):
    archive = Archive(LocalSegmentStore(tmp_path))
    assert archive.resume_offset(5) is None
    write(archive, 5, range(0, 10))
    archive.finish(5)
    write(archive, 5, range(10, 15))
    archive.finish(5)

    assert archive.resume_offset(5) == 15
    assert archive.resume_offset(4) is None


def test_crash_before_publish_leaves_nothing_archived(tmp_path):
    store = LocalSegmentStore(tmp_path)
    write(Archive(store), 5, range(0, 10))  # "crash": never finished

    restarted = Archive(LocalSegmentStore(tmp_path))
    restarted.store.discard_temporary()

    assert restarted.resume_offset(5) is None
    assert list((tmp_path / ".tmp").iterdir()) == []


def test_size_limit_finishes_segment(tmp_path):
    archive = Archive(LocalSegmentStore(tmp_path), max_raw_bytes=200)

    finished = [s for o in range(20) if (s := archive.append(5, o, TS, b"x" * 50)) is not None]

    assert finished
    assert finished[0].first_offset == 0
    assert finished[1].first_offset == finished[0].last_offset + 1


def test_age_limit_finishes_segment(tmp_path):
    archive = Archive(LocalSegmentStore(tmp_path), max_age_s=0)
    write(archive, 5, range(0, 3))

    finished = archive.finish_due()

    assert [(s.first_offset, s.last_offset) for s in finished] == [(0, 2)]
    assert archive.writers == {}


def test_abandon_discards_unfinished_segment(tmp_path):
    archive = Archive(LocalSegmentStore(tmp_path))
    archive.store.discard_temporary()
    write(archive, 5, range(0, 3))

    archive.abandon(5)

    assert archive.store.segments(5) == []
    assert list((tmp_path / ".tmp").iterdir()) == []


class FakeMessage:
    def __init__(self, partition: int, offset: int) -> None:
        self._partition, self._offset = partition, offset

    def error(self):
        return None

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def timestamp(self) -> tuple[int, int]:
        return (1, TS)

    def value(self) -> bytes:
        return b"{}"


class FakeConsumer:
    """Delivers one batch, then asks the archiver to stop. Records commits and assignments."""

    def __init__(self, archiver_ref: list, batch: list[FakeMessage], store: LocalSegmentStore):
        self.archiver_ref, self.batch, self.store = archiver_ref, batch, store
        self.commits: list[tuple[int, int, bool]] = []
        self.assigned: list[TopicPartition] = []

    def subscribe(self, topics, on_assign, on_revoke, on_lost) -> None:
        on_assign(self, [TopicPartition(topics[0], 5)])

    def assign(self, partitions) -> None:
        self.assigned = partitions

    def consume(self, num_messages, timeout):
        batch, self.batch = self.batch, []
        if not batch:
            self.archiver_ref[0].stop()
        return batch

    def commit(self, offsets, asynchronous):
        tp = offsets[0]
        published = self.store.last_offset(tp.partition)
        self.commits.append((tp.partition, tp.offset, published == tp.offset - 1))

    def close(self) -> None:
        pass


def run_archiver(tmp_path, messages):
    store = LocalSegmentStore(tmp_path)
    ref: list = []
    consumer = FakeConsumer(ref, messages, store)
    archiver = Archiver(consumer, "marketdata.kraken.raw", Archive(store))
    ref.append(archiver)
    archiver.run()
    return consumer


def test_commit_happens_only_after_segment_is_published(tmp_path):
    consumer = run_archiver(tmp_path, [FakeMessage(5, o) for o in range(0, 4)])

    assert consumer.commits == [(5, 4, True)]


def test_restart_resumes_after_archived_offsets_even_without_a_commit(tmp_path):
    run_archiver(tmp_path, [FakeMessage(5, o) for o in range(0, 4)])

    consumer = run_archiver(tmp_path, [])

    assert [(tp.partition, tp.offset) for tp in consumer.assigned] == [(5, 4)]
