"""Per-client send queue. Books are conflated to the newest per instrument and rate limited;
trades are kept in order in a bounded queue."""

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Frame:
    kind: str
    text: str
    ingested_at_ns: int | None = None


class ClientQueue:
    def __init__(self, min_book_interval_s: float, max_trades: int = 200) -> None:
        self.min_book_interval_s = min_book_interval_s
        self.max_trades = max_trades
        self._books: dict[str, Frame] = {}
        self._last_book_sent: dict[str, float] = {}
        self._trades: deque[Frame] = deque()

    def put_book(self, instrument: str, text: str, ingested_at_ns: int) -> bool:
        """Hold the newest book for an instrument. True if it replaced a book never sent."""
        replaced = instrument in self._books
        self._books[instrument] = Frame("book", text, ingested_at_ns)
        return replaced

    def put_trade(self, text: str, ingested_at_ns: int) -> bool:
        """Queue a trade. True if the queue was full and the oldest trade was dropped."""
        dropped = len(self._trades) >= self.max_trades
        if dropped:
            self._trades.popleft()
        self._trades.append(Frame("trade", text, ingested_at_ns))
        return dropped

    def drain(self, now: float) -> tuple[list[Frame], float | None]:
        """Frames to send now, and seconds until a held-back book is due (None if none is)."""
        frames = list(self._trades)
        self._trades.clear()
        wait = None
        for instrument in list(self._books):
            due_at = self._last_book_sent.get(instrument, -math.inf) + self.min_book_interval_s
            if now >= due_at:
                frames.append(self._books.pop(instrument))
                self._last_book_sent[instrument] = now
            else:
                wait = due_at - now if wait is None else min(wait, due_at - now)
        return frames, wait
