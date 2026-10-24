"""The fill engine's decisions (liquidity model A): pure logic, no Kafka, no database.

Orders never reach a real market. A market order walks Kraken's live book. A limit order
that can be filled at once from the book is; otherwise it rests until the market trades
*through* its price (strictly better), and then fills at its own limit price.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from apps.trading import pricing
from apps.trading.models import OrderType, Side
from apps.trading.pricing import Level


@dataclass(frozen=True)
class EngineOrder:
    order_id: int
    user_id: int
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None
    reserved_amount: Decimal

    @classmethod
    def from_event(cls, data: dict) -> "EngineOrder":
        return cls(
            order_id=data["order_id"],
            user_id=data["user_id"],
            symbol=data["symbol"],
            side=data["side"],
            order_type=data["type"],
            quantity=Decimal(data["quantity"]),
            limit_price=None if data["limit_price"] is None else Decimal(data["limit_price"]),
            reserved_amount=Decimal(data["reserved_amount"]),
        )


@dataclass
class Outcome:
    """What happened to an order: order.accepted, .filled, .rejected or .cancelled."""

    type: str
    order: EngineOrder
    detail: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)  # trace context, filled in by the runner

    @property
    def event_id(self) -> str:
        # Deterministic: if the engine decides again after a crash, settlement sees the same id.
        return f"{self.type}:{self.order.order_id}"

    def payload(self) -> dict:
        return {
            "v": 1,
            "event_id": self.event_id,
            "type": self.type,
            "data": {
                "order_id": self.order.order_id,
                "user_id": self.order.user_id,
                "symbol": self.order.symbol,
                "side": self.order.side,
                **self.detail,
            },
        }


@dataclass
class Book:
    bids: list[list[str]]  # [[price, quantity], ...] as published: best first, strings
    asks: list[list[str]]
    ingested_at_ns: int

    def side(self, taker_side: str) -> list[Level]:
        """The levels a taker on `taker_side` trades against: buyers take asks."""
        levels = self.asks if taker_side == Side.BUY else self.bids
        return [(Decimal(price), Decimal(quantity)) for price, quantity in levels]


class FillEngine:
    def __init__(self, fee_rate: Decimal, max_book_age_s: float = 5.0, now_ns=time.time_ns):
        self.fee_rate = fee_rate
        self.max_book_age_ns = max_book_age_s * 1e9
        self.now_ns = now_ns
        self.books: dict[str, Book] = {}
        self.resting: dict[str, dict[int, EngineOrder]] = {}
        self.seen: set[int] = set()

    def on_book(self, symbol: str, bids: list, asks: list, ingested_at_ns: int) -> None:
        self.books[symbol] = Book(bids, asks, ingested_at_ns)

    def fresh_book(self, symbol: str) -> Book | None:
        book = self.books.get(symbol)
        if book is None or self.now_ns() - book.ingested_at_ns > self.max_book_age_ns:
            return None
        return book

    def on_placed(self, order: EngineOrder) -> list[Outcome]:
        if order.order_id in self.seen:
            return []  # a redelivered command: already decided
        self.seen.add(order.order_id)
        book = self.fresh_book(order.symbol)
        if order.order_type == OrderType.MARKET:
            if book is None:
                return [self._reject(order, "market_unavailable")]
            fills = pricing.take(book.side(order.side), order.quantity)
            if fills is None:
                return [self._reject(order, "insufficient_liquidity")]
            return [self._fill(order, fills, "taker")]
        if book is not None:
            fills = pricing.take(book.side(order.side), order.quantity, self._within_limit(order))
            if fills is not None:
                return [self._fill(order, fills, "taker")]
        self.resting.setdefault(order.symbol, {})[order.order_id] = order
        return [Outcome("order.accepted", order)]

    def on_trade(self, symbol: str, price: Decimal) -> list[Outcome]:
        """Fill every resting order this trade went *through*, at the order's own price."""
        outcomes = []
        resting = self.resting.get(symbol, {})
        for order in list(resting.values()):
            assert order.limit_price is not None
            through = (
                price < order.limit_price if order.side == Side.BUY else price > order.limit_price
            )
            if through:
                del resting[order.order_id]
                outcomes.append(self._fill(order, [(order.limit_price, order.quantity)], "maker"))
        return outcomes

    def on_cancel(self, order_id: int, symbol: str) -> list[Outcome]:
        order = self.resting.get(symbol, {}).pop(order_id, None)
        return [] if order is None else [Outcome("order.cancelled", order)]

    def recover(self, orders: list[EngineOrder], cancel_requested: set[int]) -> list[Outcome]:
        """Rebuild state after a restart from the orders the database says aren't finished."""
        outcomes = []
        for order in orders:
            outcomes += self.on_placed(order)
            if order.order_id in cancel_requested:
                outcomes += self.on_cancel(order.order_id, order.symbol)
        return outcomes

    def resting_count(self) -> int:
        return sum(len(orders) for orders in self.resting.values())

    def _within_limit(self, order: EngineOrder) -> Callable[[Decimal], bool]:
        limit = order.limit_price
        assert limit is not None
        if order.side == Side.BUY:
            return lambda price: price <= limit
        return lambda price: price >= limit

    def _fill(self, order: EngineOrder, fills: list[Level], liquidity: str) -> Outcome:
        gross = pricing.notional(fills)
        if order.side == Side.BUY:
            amount, fee = pricing.buy_charge(gross, self.fee_rate)
            if amount + fee > order.reserved_amount:
                return self._reject(order, "price_moved")
        else:  # a seller receives proceeds rounded down, and pays a fee rounded up
            amount = pricing.round_down(gross, 2)
            fee = pricing.round_up(gross * self.fee_rate, 2)
        return Outcome(
            "order.filled",
            order,
            {
                "quantity": pricing.plain(order.quantity),
                "average_price": pricing.plain(gross / order.quantity),
                "quote_amount": pricing.plain(amount),
                "fee": pricing.plain(fee),
                "liquidity": liquidity,
                "fills": [[pricing.plain(price), pricing.plain(size)] for price, size in fills],
            },
        )

    def _reject(self, order: EngineOrder, reason: str) -> Outcome:
        return Outcome("order.rejected", order, {"reason": reason})
