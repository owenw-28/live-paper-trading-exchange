"""Archive of raw venue messages as compressed segment files named by offset range.

Each partition is written to its own segment. A segment is built in a temporary file, then
fsynced and atomically renamed to a name holding its first and last offset. On startup each
partition resumes after its highest archived offset, so a crash can neither lose a message
nor archive it twice.
"""

import io
import json
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import zstandard

SEGMENT_NAME = re.compile(r"offsets-(\d{12})-(\d{12})\.jsonl\.zst")


@dataclass(frozen=True)
class Segment:
    partition: int
    first_offset: int
    last_offset: int
    path: Path
    messages: int
    raw_bytes: int


class LocalSegmentStore:
    """Keeps finished segments under a root directory on the local filesystem."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.tmp_dir = root / ".tmp"

    def discard_temporary(self) -> None:
        """Delete half-written segments left behind by a crash."""
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        for leftover in self.tmp_dir.iterdir():
            leftover.unlink()

    def temp_path(self, partition: int, first_offset: int) -> Path:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        return self.tmp_dir / f"partition-{partition}-{first_offset}.tmp"

    def publish(self, temp: Path, relative: Path) -> Path:
        final = self.root / relative
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, final)
        _fsync_directory(final.parent)
        return final

    def partitions(self) -> list[int]:
        return sorted(int(path.name.removeprefix("partition-")) for path in self._partition_dirs())

    def segments(self, partition: int) -> list[Path]:
        paths = (self.root / f"partition-{partition}").glob("*/offsets-*.jsonl.zst")
        return sorted(paths, key=lambda path: segment_range(path)[0])

    def last_offset(self, partition: int) -> int | None:
        return max((segment_range(path)[1] for path in self.segments(partition)), default=None)

    def _partition_dirs(self) -> list[Path]:
        return [path for path in self.root.glob("partition-*") if path.is_dir()]


class SegmentWriter:
    """Builds one segment for one partition in a temporary file."""

    def __init__(self, path: Path, partition: int, first_offset: int, first_ts_ms: int) -> None:
        self.path = path
        self.partition = partition
        self.first_offset = first_offset
        self.last_offset = first_offset - 1
        self.first_ts_ms = first_ts_ms
        self.opened_at = time.monotonic()
        self.messages = 0
        self.raw_bytes = 0
        self._file = path.open("wb")
        self._zstd = zstandard.ZstdCompressor().stream_writer(self._file, closefd=False)

    def append(self, offset: int, timestamp_ms: int, value: bytes) -> None:
        record = {
            "partition": self.partition,
            "offset": offset,
            "timestamp_ms": timestamp_ms,
            "raw": value.decode(),
        }
        line = json.dumps(record, separators=(",", ":")).encode() + b"\n"
        self._zstd.write(line)
        self.last_offset = offset
        self.messages += 1
        self.raw_bytes += len(line)

    def close(self) -> None:
        """Finish the compressed stream and force the file's bytes onto disk."""
        self._zstd.close()
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()

    def abandon(self) -> None:
        self._zstd.close()
        self._file.close()
        self.path.unlink(missing_ok=True)

    def relative_path(self) -> Path:
        day = datetime.fromtimestamp(self.first_ts_ms / 1000, tz=UTC).date().isoformat()
        name = f"offsets-{self.first_offset:012d}-{self.last_offset:012d}.jsonl.zst"
        return Path(f"partition-{self.partition}") / day / name


class Archive:
    """Routes messages into per-partition segments and decides when each segment is finished."""

    def __init__(
        self,
        store: LocalSegmentStore,
        max_age_s: float = 60.0,
        max_raw_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.store = store
        self.max_age_s = max_age_s
        self.max_raw_bytes = max_raw_bytes
        self.writers: dict[int, SegmentWriter] = {}

    def resume_offset(self, partition: int) -> int | None:
        """The first offset not yet archived for this partition, if anything is archived."""
        last = self.store.last_offset(partition)
        return None if last is None else last + 1

    def append(
        self, partition: int, offset: int, timestamp_ms: int, value: bytes
    ) -> Segment | None:
        writer = self.writers.get(partition)
        if writer is None:
            path = self.store.temp_path(partition, offset)
            writer = self.writers[partition] = SegmentWriter(path, partition, offset, timestamp_ms)
        writer.append(offset, timestamp_ms, value)
        if writer.raw_bytes >= self.max_raw_bytes:
            return self.finish(partition)
        return None

    def finish_due(self) -> list[Segment]:
        now = time.monotonic()
        due = [p for p, writer in self.writers.items() if now - writer.opened_at >= self.max_age_s]
        return [self.finish(partition) for partition in due]

    def finish_all(self) -> list[Segment]:
        return [self.finish(partition) for partition in list(self.writers)]

    def finish(self, partition: int) -> Segment:
        writer = self.writers.pop(partition)
        writer.close()
        path = self.store.publish(writer.path, writer.relative_path())
        return Segment(
            partition,
            writer.first_offset,
            writer.last_offset,
            path,
            writer.messages,
            writer.raw_bytes,
        )

    def abandon(self, partition: int) -> None:
        writer = self.writers.pop(partition, None)
        if writer is not None:
            writer.abandon()


def segment_range(path: Path) -> tuple[int, int]:
    match = SEGMENT_NAME.fullmatch(path.name)
    if match is None:
        raise ValueError(f"not a segment file: {path}")
    return int(match[1]), int(match[2])


def read_segment(path: Path) -> Iterator[dict]:
    with path.open("rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as reader:
        for line in io.TextIOWrapper(reader, encoding="utf-8"):
            yield json.loads(line)


def _fsync_directory(path: Path) -> None:
    """Make a rename inside this directory durable, not just visible."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
