"""Settlement: applying the fill engine's outcomes to orders and the ledger.

Outcomes can arrive more than once (redelivery, or the engine deciding again after a crash),
and after a crash the engine may even decide differently. The first final outcome for an
order wins: each one is applied under a row lock, only if the order's current status allows
it, and its ledger postings are unique per order.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.ledger import services as ledger
from apps.ledger.models import AccountKind, TransactionKind
from apps.ledger.services import Leg
from apps.trading.instruments import INSTRUMENTS
from apps.trading.models import FINAL_STATUSES, Order, OrderStatus, Side

logger = logging.getLogger(__name__)

ACTIVE = {OrderStatus.PENDING, OrderStatus.OPEN}

# Outcome type -> (statuses it may be applied in, the status it moves the order to)
TRANSITIONS = {
    "order.accepted": ({OrderStatus.PENDING}, OrderStatus.OPEN),
    "order.filled": (ACTIVE, OrderStatus.FILLED),
    "order.rejected": (ACTIVE, OrderStatus.REJECTED),
    "order.cancelled": (ACTIVE, OrderStatus.CANCELLED),
}


def settle(event: dict) -> Order | None:
    """Apply one outcome. Returns the changed order, or None if there was nothing to apply."""
    transition = TRANSITIONS.get(event["type"])
    if transition is None:
        logger.warning("Unknown outcome %s", event["type"])
        return None
    allowed, new_status = transition
    data = event["data"]
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(id=data["order_id"]).first()
        if order is None:
            logger.warning("Outcome %s for an unknown order", event["event_id"])
            return None
        if order.status not in allowed:
            return None  # a repeat, or an order an earlier final outcome already settled
        if new_status == OrderStatus.FILLED:
            _post_fill(order, data)
            order.filled_quantity = Decimal(data["quantity"])
            order.average_price = Decimal(data["average_price"])
            order.quote_amount = Decimal(data["quote_amount"])
            order.fee = Decimal(data["fee"])
        elif new_status in FINAL_STATUSES:  # rejected or cancelled: hand everything back
            ledger.release(
                order.user, order.reserved_asset, order.reserved_amount, f"order:{order.id}"
            )
            order.reject_reason = data.get("reason", "")
        if new_status in FINAL_STATUSES:
            order.settled_at = timezone.now()
        order.status = new_status
        order.save()
    return order


def _post_fill(order: Order, data: dict) -> None:
    """One balanced transaction: pay for the fill, collect the fee, return what wasn't needed."""
    instrument = INSTRUMENTS[order.symbol]
    base, quote = instrument.base, instrument.quote
    quantity = Decimal(data["quantity"])
    amount = Decimal(data["quote_amount"])
    fee = Decimal(data["fee"])

    def mine(asset: str, kind: str):
        return ledger.account(order.user, asset, kind)

    def market(asset: str):
        return ledger.system_account(asset, AccountKind.MARKET)

    fees = ledger.system_account(quote, AccountKind.FEES)
    if order.side == Side.BUY:
        unused = order.reserved_amount - amount - fee
        if unused < 0:
            raise ledger.LedgerError(f"order {order.id} fill costs more than was reserved")
        legs = [
            Leg(mine(quote, AccountKind.RESERVED), -order.reserved_amount),
            Leg(market(quote), amount),
            Leg(fees, fee),
            Leg(mine(quote, AccountKind.AVAILABLE), unused),
            Leg(market(base), -quantity),
            Leg(mine(base, AccountKind.AVAILABLE), quantity),
        ]
    else:  # the fee comes out of the proceeds
        legs = [
            Leg(mine(base, AccountKind.RESERVED), -quantity),
            Leg(market(base), quantity),
            Leg(market(quote), -amount),
            Leg(mine(quote, AccountKind.AVAILABLE), amount - fee),
            Leg(fees, fee),
        ]
    ledger.post(TransactionKind.FILL, f"order:{order.id}", [leg for leg in legs if leg.amount])
