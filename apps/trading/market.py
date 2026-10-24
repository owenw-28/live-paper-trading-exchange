"""The latest verified order book."""

import json
import time
from decimal import Decimal
from functools import cache

import redis
from django.conf import settings

from apps.marketdata.live import depth_key
from apps.trading.pricing import Level

MAX_BOOK_AGE_S = 5.0


@cache
def _client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def latest_asks(instrument: str) -> list[Level] | None:
    """Best asks first, or None if there's no book or it's too old to price an order on."""
    text = _client().get(depth_key(instrument))
    if not isinstance(text, str):
        return None
    book = json.loads(text)
    if time.time_ns() - book["ingested_at_ns"] > MAX_BOOK_AGE_S * 1e9:
        return None
    return [(Decimal(price), Decimal(qty)) for price, qty in book["asks"]]
