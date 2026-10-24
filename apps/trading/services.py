"""Placing and cancelling orders. Each change commits together with its outbox event."""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from apps.core import outbox
from apps.ledger import services as ledger
from apps.ledger.models import Asset
from apps.ledger.services import InsufficientFunds
from apps.marketdata.topics import instrument_key
from apps.trading import market, pricing
from apps.trading.instruments import INSTRUMENTS
from apps.trading.models import FINAL_STATUSES, Order, OrderType, Side
from apps.trading.topics import ORDER_COMMANDS


class OrderRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IdempotencyConflict(Exception):
    """The idempotency key was already used for a different order."""


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None

    def matches(self, order: Order) -> bool:
        return (order.symbol, order.side, order.order_type, order.quantity, order.limit_price) == (
            self.symbol,
            self.side,
            self.order_type,
            self.quantity,
            self.limit_price,
        )


def place_order(user: User, request: OrderRequest, idempotency_key: str) -> tuple[Order, bool]:
    """Place an order, or return the one already placed with this key. (order, created)."""
    existing = _existing(user, request, idempotency_key)
    if existing is not None:
        return existing, False
    asset, amount = _reservation(request)
    try:
        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                idempotency_key=idempotency_key,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                limit_price=request.limit_price,
                reserved_asset=asset,
                reserved_amount=amount,
            )
            ledger.reserve(user, asset, amount, f"order:{order.id}")
            outbox.enqueue(
                ORDER_COMMANDS.name,
                instrument_key("kraken", order.symbol),
                "order.placed",
                order_event(order),
            )
    except InsufficientFunds:
        raise OrderRejected("insufficient_funds", f"Not enough {asset} available.") from None
    except IntegrityError:  # the same key raced us: the other request created the order
        winner = _existing(user, request, idempotency_key)
        if winner is None:
            raise
        return winner, False
    return order, True


def cancel_order(user: User, order_id: int) -> Order:
    """Ask the fill engine to cancel. It, not the API, decides: it may be filling right now."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(user=user, id=order_id)
        if order.status in FINAL_STATUSES:
            raise OrderRejected("not_cancellable", f"The order is already {order.status}.")
        if not order.cancel_requested:
            order.cancel_requested = True
            order.save(update_fields=["cancel_requested", "updated_at"])
            outbox.enqueue(
                ORDER_COMMANDS.name,
                instrument_key("kraken", order.symbol),
                "order.cancel_requested",
                {"order_id": order.id, "user_id": order.user_id, "symbol": order.symbol},
            )
    return order


def order_event(order: Order) -> dict:
    return {
        "order_id": order.id,
        "user_id": order.user_id,
        "symbol": order.symbol,
        "side": order.side,
        "type": order.order_type,
        "quantity": str(order.quantity),
        "limit_price": None if order.limit_price is None else str(order.limit_price),
        "reserved_asset": order.reserved_asset,
        "reserved_amount": str(order.reserved_amount),
    }


def _existing(user: User, request: OrderRequest, idempotency_key: str) -> Order | None:
    order = Order.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if order is not None and not request.matches(order):
        raise IdempotencyConflict
    return order


def _reservation(request: OrderRequest) -> tuple[Asset, Decimal]:
    instrument = INSTRUMENTS[request.symbol]
    fee_rate: Decimal = settings.TRADING_FEE_RATE
    if request.side == Side.SELL:
        return instrument.base, request.quantity
    if request.order_type == OrderType.LIMIT:
        assert request.limit_price is not None
        return instrument.quote, pricing.limit_buy_reservation(
            request.quantity, request.limit_price, fee_rate
        )
    asks = market.latest_asks(instrument_key("kraken", request.symbol))
    if asks is None:
        raise OrderRejected("market_unavailable", "No live prices right now. Try again shortly.")
    amount = pricing.market_buy_reservation(
        asks, request.quantity, fee_rate, settings.MARKET_BUY_PRICE_BUFFER
    )
    if amount is None:
        raise OrderRejected("insufficient_liquidity", "The order is larger than the visible book.")
    return instrument.quote, amount
