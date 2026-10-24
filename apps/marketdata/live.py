"""Live market state for clients: the latest book and recent trades in Redis, and the
Channels group each instrument's updates are broadcast to."""

import json
from typing import cast

import redis.asyncio as redis

BOOK_TTL_S = 30
RECENT_TRADES = 50
DISPLAY_DEPTH = 10  # levels per side sent to browsers; full book stays server-side


def frame(kind: str, event: dict) -> str:
    """The JSON text sent to browsers: {"type": "book" | "trade", "data": event}."""
    return json.dumps({"type": kind, "data": event}, separators=(",", ":"))


def group_name(instrument: str) -> str:
    """Channels group for an instrument. Group names can't contain '/', so BTC/USD -> BTC-USD."""
    return "market." + instrument.replace(":", ".").replace("/", "-")


class LiveState:
    def __init__(self, client: redis.Redis) -> None:
        self.redis = client

    @classmethod
    def from_url(cls, url: str) -> "LiveState":
        return cls(redis.from_url(url, decode_responses=True))

    async def save_book(self, instrument: str, text: str) -> None:
        await self.redis.set(book_key(instrument), text, ex=BOOK_TTL_S)

    async def save_depth(self, instrument: str, event: str) -> None:
        """The full-depth book event, for pricing orders."""
        await self.redis.set(depth_key(instrument), event, ex=BOOK_TTL_S)

    async def save_trade(self, instrument: str, text: str) -> None:
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.lpush(_trades_key(instrument), text)
            pipe.ltrim(_trades_key(instrument), 0, RECENT_TRADES - 1)
            await pipe.execute()

    async def snapshot(self, instrument: str) -> list[str]:
        """Frames a newly connected client needs: recent trades oldest first, then the book."""
        trades = cast(list[str], await self.redis.lrange(_trades_key(instrument), 0, -1))
        book = cast(str | None, await self.redis.get(book_key(instrument)))
        return list(reversed(trades)) + ([book] if book is not None else [])


def book_key(instrument: str) -> str:
    return f"live:book:{instrument}"


def depth_key(instrument: str) -> str:
    return f"live:depth:{instrument}"


def _trades_key(instrument: str) -> str:
    return f"live:trades:{instrument}"
