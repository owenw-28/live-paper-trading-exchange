import uuid
from decimal import Decimal as D

import pytest
from django.contrib.auth.models import User
from django.db import transaction
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.ledger import services as ledger
from apps.ledger.models import AccountKind, Asset, Transaction, TransactionKind
from apps.trading.engine import EngineOrder, FillEngine, Outcome
from apps.trading.models import Order, OrderStatus
from apps.trading.services import OrderRequest, order_event, place_order
from apps.trading.settlement import settle

pytestmark = pytest.mark.django_db

FEE = D("0.0025")
NOW = 1_000_000_000_000


def make_user(name: str = "owen", btc: str | None = None) -> User:
    user = User.objects.create(username=name)
    ledger.fund_new_user(user)
    if btc is not None:
        ledger.transfer(
            TransactionKind.DEPOSIT,
            f"test:{name}:BTC",
            ledger.system_account(Asset.BTC, AccountKind.FUNDING),
            ledger.account(user, Asset.BTC, AccountKind.AVAILABLE),
            D(btc),
        )
    return user


def limit(user: User, side: str, quantity: str, price: str) -> Order:
    request = OrderRequest("BTC/USD", side, "limit", D(quantity), D(price))
    order, _ = place_order(user, request, uuid.uuid4().hex)
    return order


def filled(order: Order, bids=(), asks=()) -> dict:
    """The order.filled event the real engine publishes for `order` against this book."""
    engine = FillEngine(FEE, now_ns=lambda: NOW)
    engine.on_book(order.symbol, list(bids), list(asks), NOW)
    [outcome] = engine.on_placed(EngineOrder.from_event(order_event(order)))
    assert outcome.type == "order.filled"
    return outcome.payload()


def outcome(order: Order, type: str, **detail) -> dict:
    return Outcome(type, EngineOrder.from_event(order_event(order)), detail).payload()


def usd(user: User) -> dict:
    return ledger.balances(user)[Asset.USD]


def test_buy_fill_pays_the_market_and_the_fee_and_returns_what_was_not_needed():
    owen = make_user()
    order = limit(owen, "buy", "0.5", "80000.1")  # reserves 40000.05 + 100.01 = 40100.06

    settled = settle(filled(order, asks=[["80000.0", "1"]]))  # costs 40000.00 + 100.00 fee

    assert settled is not None and settled.status == OrderStatus.FILLED
    assert (settled.quote_amount, settled.fee, settled.filled_quantity) == (40000, 100, D("0.5"))
    assert settled.settled_at is not None
    assert usd(owen) == {"available": D("59900.00"), "reserved": 0}  # 0.06 came back
    assert ledger.balances(owen)[Asset.BTC]["available"] == D("0.5")
    assert ledger.balance_of(ledger.system_account(Asset.USD, AccountKind.FEES).id) == 100
    assert ledger.imbalance() == {}


def test_sell_fill_pays_proceeds_minus_the_fee():
    owen = make_user(btc="1")
    order = limit(owen, "sell", "0.5", "80000.0")

    settle(filled(order, bids=[["80000.1", "1"]]))  # 40000.05, fee 100.000125 rounded up

    assert usd(owen) == {"available": D("100000") + D("40000.05") - D("100.01"), "reserved": 0}
    assert ledger.balances(owen)[Asset.BTC] == {"available": D("0.5"), "reserved": 0}
    assert ledger.imbalance() == {}


@pytest.mark.parametrize(
    ("type", "detail", "status"),
    [
        ("order.rejected", {"reason": "price_moved"}, OrderStatus.REJECTED),
        ("order.cancelled", {}, OrderStatus.CANCELLED),
    ],
)
def test_rejected_and_cancelled_orders_get_their_whole_reservation_back(type, detail, status):
    owen = make_user()
    order = limit(owen, "buy", "0.5", "80000.1")

    settled = settle(outcome(order, type, **detail))

    assert settled is not None and settled.status == status
    assert settled.reject_reason == detail.get("reason", "")
    assert usd(owen) == {"available": D("100000.00"), "reserved": 0}


def test_accepted_opens_a_pending_order_without_moving_money():
    owen = make_user()
    order = limit(owen, "buy", "0.5", "1000.0")
    before = usd(owen)

    settled = settle(outcome(order, "order.accepted"))

    assert settled is not None and settled.status == OrderStatus.OPEN
    assert settled.settled_at is None
    assert usd(owen) == before
    assert settle(outcome(order, "order.accepted")) is None  # a repeat


def test_a_repeated_outcome_is_applied_once():
    owen = make_user()
    order = limit(owen, "buy", "0.5", "80000.1")
    event = filled(order, asks=[["80000.0", "1"]])

    settle(event)
    assert settle(event) is None

    assert Transaction.objects.filter(kind=TransactionKind.FILL).count() == 1
    assert usd(owen)["available"] == D("59900.00")


@pytest.mark.parametrize(
    ("first", "second", "status"),
    [("filled", "rejected", OrderStatus.FILLED), ("rejected", "filled", OrderStatus.REJECTED)],
)
def test_the_first_final_outcome_wins(first, second, status):
    # The engine filled, crashed before committing, and on restart decided differently.
    owen = make_user()
    order = limit(owen, "buy", "0.5", "80000.1")
    events = {
        "filled": filled(order, asks=[["80000.0", "1"]]),
        "rejected": outcome(order, "order.rejected", reason="price_moved"),
    }

    settle(events[first])
    assert settle(events[second]) is None

    assert Order.objects.get(id=order.id).status == status
    assert Transaction.objects.filter(reference=f"order:{order.id}").count() == 2  # reserve + 1
    assert ledger.imbalance() == {}


def test_accepted_after_a_final_outcome_is_ignored():
    owen = make_user()
    order = limit(owen, "buy", "0.5", "80000.1")
    settle(filled(order, asks=[["80000.0", "1"]]))

    assert settle(outcome(order, "order.accepted")) is None
    assert Order.objects.get(id=order.id).status == OrderStatus.FILLED


def test_outcomes_for_unknown_orders_or_types_are_skipped():
    owen = make_user()
    order = limit(owen, "buy", "0.5", "1000.0")
    unknown = outcome(order, "order.cancelled")
    unknown["data"]["order_id"] = order.id + 1000

    assert settle(unknown) is None
    assert settle(outcome(order, "order.expired")) is None


# Model-based property: any sequence of outcomes, with repeats and conflicts, settles each
# order by its first final outcome, and the ledger always balances.

ORDERS = 3
TYPES = ["order.accepted", "order.filled", "order.rejected", "order.cancelled"]


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.tuples(st.integers(0, ORDERS - 1), st.sampled_from(TYPES)), max_size=15))
def test_any_outcome_sequence_settles_like_the_model(sequence):
    with transaction.atomic():
        check(sequence)
        transaction.set_rollback(True)  # each example starts from an empty database


def check(sequence: list[tuple[int, str]]) -> None:
    owen = make_user()
    orders = [limit(owen, "buy", "0.01", f"{100 + i}.0") for i in range(ORDERS)]
    events = {
        (i, type): filled(o, asks=[["99.0", "1"]])
        if type == "order.filled"
        else outcome(o, type, reason="price_moved")
        for i, o in enumerate(orders)
        for type in TYPES
    }
    status = [OrderStatus.PENDING] * ORDERS
    moves = {
        "order.accepted": OrderStatus.OPEN,
        "order.filled": OrderStatus.FILLED,
        "order.rejected": OrderStatus.REJECTED,
        "order.cancelled": OrderStatus.CANCELLED,
    }

    for i, type in sequence:
        settle(events[(i, type)])
        allowed = status[i] == OrderStatus.PENDING or (
            status[i] == OrderStatus.OPEN and type != "order.accepted"
        )
        if allowed:
            status[i] = moves[type]
        assert ledger.imbalance() == {}

    assert [Order.objects.get(id=o.id).status for o in orders] == status
    reserved = spent = bought = D(0)
    for i, order in enumerate(orders):
        if status[i] in (OrderStatus.PENDING, OrderStatus.OPEN):
            reserved += order.reserved_amount
        elif status[i] == OrderStatus.FILLED:
            fill = events[(i, "order.filled")]["data"]
            spent += D(fill["quote_amount"]) + D(fill["fee"])
            bought += order.quantity
    assert usd(owen) == {"available": D("100000.00") - reserved - spent, "reserved": reserved}
    assert ledger.balances(owen).get(Asset.BTC, {"available": 0})["available"] == bought
