from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from apps.trading.engine import EngineOrder, FillEngine
from apps.trading.pricing import limit_buy_reservation

NOW = 1_000_000_000_000
FEE = D("0.0025")
BIDS = [["99.9", "1"], ["99.5", "2"]]
ASKS = [["100.0", "1"], ["100.5", "2"]]


def engine(book_age_s: float = 0) -> FillEngine:
    e = FillEngine(FEE, now_ns=lambda: NOW)
    e.on_book("BTC/USD", BIDS, ASKS, NOW - int(book_age_s * 1e9))
    return e


def order(side="buy", order_type="market", quantity="1", limit=None, reserved="1000000", n=1):
    return EngineOrder(
        order_id=n,
        user_id=7,
        symbol="BTC/USD",
        side=side,
        order_type=order_type,
        quantity=D(quantity),
        limit_price=None if limit is None else D(limit),
        reserved_amount=D(reserved),
    )


def only(outcomes):
    assert len(outcomes) == 1
    return outcomes[0]


def test_market_buy_walks_the_asks_and_rounds_against_the_buyer():
    filled = only(engine().on_placed(order(quantity="1.5")))

    assert filled.type == "order.filled"
    assert filled.detail["fills"] == [["100.0", "1"], ["100.5", "0.5"]]
    assert filled.detail["quote_amount"] == "150.25"
    assert filled.detail["fee"] == "0.38"  # 150.25 * 0.25% = 0.375625, rounded up
    assert filled.detail["liquidity"] == "taker"


def test_market_sell_walks_the_bids_and_rounds_proceeds_down():
    filled = only(engine().on_placed(order(side="sell", quantity="1.00000001")))

    assert filled.detail["fills"] == [["99.9", "1"], ["99.5", "0.00000001"]]
    assert filled.detail["quote_amount"] == "99.90"  # 99.900000995 rounded down


@pytest.mark.parametrize(
    ("book_age_s", "quantity", "reserved", "reason"),
    [
        (10, "1", "1000000", "market_unavailable"),  # the book is stale
        (0, "3.1", "1000000", "insufficient_liquidity"),  # bigger than the whole book
        (0, "1", "100.00", "price_moved"),  # 100 + fee no longer fits the reservation
    ],
)
def test_market_orders_are_rejected_rather_than_filled_badly(
    book_age_s, quantity, reserved, reason
):
    rejected = only(engine(book_age_s).on_placed(order(quantity=quantity, reserved=reserved)))

    assert (rejected.type, rejected.detail["reason"]) == ("order.rejected", reason)


def test_marketable_limit_buy_fills_at_once_but_never_above_its_limit():
    filled = only(engine().on_placed(order(order_type="limit", quantity="2", limit="100.5")))

    assert filled.detail["fills"] == [["100.0", "1"], ["100.5", "1"]]


def test_limit_that_cannot_fill_now_rests_whole():
    e = engine()

    accepted = only(e.on_placed(order(order_type="limit", quantity="2", limit="100.0")))

    assert accepted.type == "order.accepted"
    assert e.resting_count() == 1


def test_resting_buy_fills_only_when_a_trade_goes_through_its_price():
    e = engine()
    e.on_placed(order(order_type="limit", limit="99.0"))

    assert e.on_trade("BTC/USD", D("99.0")) == []  # touching the price is not enough
    filled = only(e.on_trade("BTC/USD", D("98.9")))

    assert filled.detail["fills"] == [["99.0", "1"]]  # at the order's own price
    assert filled.detail["liquidity"] == "maker"
    assert e.resting_count() == 0


def test_resting_sell_fills_when_a_trade_goes_above_it():
    e = engine()
    e.on_placed(order(side="sell", order_type="limit", limit="101.0"))

    assert e.on_trade("BTC/USD", D("101.0")) == []
    assert only(e.on_trade("BTC/USD", D("101.1"))).type == "order.filled"


def test_cancel_removes_a_resting_order_and_ignores_unknown_ones():
    e = engine()
    e.on_placed(order(order_type="limit", limit="99.0"))

    assert only(e.on_cancel(1, "BTC/USD")).type == "order.cancelled"
    assert e.on_cancel(1, "BTC/USD") == []
    assert e.on_trade("BTC/USD", D("1")) == []


def test_a_redelivered_command_is_decided_only_once():
    e = engine()

    assert len(e.on_placed(order())) == 1
    assert e.on_placed(order()) == []


def test_outcome_ids_are_deterministic_so_settlement_can_spot_repeats():
    first = only(engine().on_placed(order()))
    after_restart = only(engine().on_placed(order()))

    assert first.event_id == after_restart.event_id == "order.filled:1"


def test_recovery_rebuilds_resting_orders_and_applies_pending_cancels():
    e = engine()
    resting = order(order_type="limit", limit="99.0", n=1)
    cancelled = order(order_type="limit", limit="98.0", n=2)

    outcomes = e.recover([resting, cancelled], cancel_requested={2})

    assert [(o.type, o.order.order_id) for o in outcomes] == [
        ("order.accepted", 1),
        ("order.accepted", 2),
        ("order.cancelled", 2),
    ]
    assert e.resting_count() == 1


prices = st.integers(1, 20_000).map(lambda n: D(n) / 10)  # BTC/USD ticks of 0.1
sizes = st.integers(1, 10**8).map(lambda n: D(n) / 10**8)


@given(
    asks=st.lists(st.tuples(prices, sizes), min_size=1, max_size=20),
    quantity=sizes,
    limit=prices,
)
def test_limit_buys_never_pay_above_the_limit_or_exceed_the_reservation(asks, quantity, limit):
    book = [[str(p), str(q)] for p, q in sorted(asks)]
    e = FillEngine(FEE, now_ns=lambda: NOW)
    e.on_book("BTC/USD", [], book, NOW)
    reserved = limit_buy_reservation(quantity, limit, FEE)

    outcome = only(
        e.on_placed(
            order(
                order_type="limit", quantity=str(quantity), limit=str(limit), reserved=str(reserved)
            )
        )
    )

    if outcome.type == "order.filled":
        fills = [(D(p), D(q)) for p, q in outcome.detail["fills"]]
        assert all(price <= limit for price, _ in fills)
        assert sum(q for _, q in fills) == quantity
        assert D(outcome.detail["quote_amount"]) + D(outcome.detail["fee"]) <= reserved
    else:
        assert outcome.type == "order.accepted"
