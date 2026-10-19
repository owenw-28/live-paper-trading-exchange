from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.marketdata.archive import LocalSegmentStore, read_segment, segment_range


class Command(BaseCommand):
    help = "Check that every archived partition has contiguous offsets with no gaps or repeats."

    def handle(self, *args, **options):
        store = LocalSegmentStore(settings.ARCHIVE_ROOT / "kraken" / "raw")
        problems = []
        for partition in store.partitions():
            expected = None
            count = 0
            segments = store.segments(partition)
            for path in segments:
                first, last = segment_range(path)
                if expected is not None and first != expected:
                    problems.append(
                        f"partition {partition}: expected offset {expected}, {path.name}"
                    )
                offsets = [record["offset"] for record in read_segment(path)]
                if offsets != list(range(first, last + 1)):
                    problems.append(f"partition {partition}: {path.name} content != its name")
                count += len(offsets)
                expected = last + 1
            first_offset = segment_range(segments[0])[0] if segments else None
            self.stdout.write(
                f"partition {partition}: {len(segments)} segments, {count} messages, "
                f"offsets {first_offset}..{expected - 1 if expected else None}"
            )
        if problems:
            raise CommandError("Archive problems:\n" + "\n".join(problems))
        self.stdout.write(self.style.SUCCESS("Archive OK: no gaps, no repeats"))
