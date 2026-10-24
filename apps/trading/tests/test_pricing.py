from decimal import Decimal as D

from apps.trading.pricing import (
    cost_to_buy,
    limit_buy_reservation,
    market_buy_reservation,
    round_up,
)

ASKS = [(D("100"), D("1")), (D("101"), D("1")), (D("105"), D("2"))]


def test_cost_walks_the_book_best_price_first():
    assert cost_to_buy(ASKS, D("1.5")) == D("150.5")  # 1 @ 100 + 0.5 @ 101


def test_cost_is_none_when_the_book_runs_out():
    assert cost_to_buy(ASKS, D("4.00000001")) is None


def test_round_up_never_rounds_down():
    assert round_up(D("10.001"), 2) == D("10.01")
    assert round_up(D("10.00"), 2) == D("10.00")


def test_limit_buy_reserves_the_worst_case_cost_including_fee():
    # 0.5 * 80000.1 = 40000.05; with the 0.25% fee: 40100.050125 -> rounded up to the cent
    assert limit_buy_reservation(D("0.5"), D("80000.1"), D("0.0025")) == D("40100.06")


def test_market_buy_adds_buffer_and_fee():
    # 150.5 * 1.02 * 1.0025 = 153.892...
    assert market_buy_reservation(ASKS, D("1.5"), D("0.0025"), D("0.02")) == D("153.90")
    assert market_buy_reservation(ASKS, D("10"), D("0.0025"), D("0.02")) is None
