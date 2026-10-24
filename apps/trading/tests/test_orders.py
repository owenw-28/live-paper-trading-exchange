from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import OutboxEvent
from apps.ledger import services as ledger
from apps.ledger.models import AccountKind, Asset, Entry
from apps.trading import market
from apps.trading.models import Order, OrderStatus

pytestmark = pytest.mark.django_db

LIMIT_BUY = {
    "symbol": "BTC/USD",
    "side": "buy",
    "type": "limit",
    "quantity": "0.5",
    "limit_price": "80000.1",
}


def make_user(name: str = "owen") -> User:
    user = User.objects.create_user(name, password="correct-horse-battery-staple")
    ledger.fund_new_user(user)
    return user


def logged_in(user: User) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def owen() -> User:
    return make_user()


@pytest.fixture
def client(owen) -> APIClient:
    return logged_in(owen)


@pytest.fixture(autouse=True)
def book(monkeypatch):
    asks = [(Decimal("100"), Decimal("1")), (Decimal("101"), Decimal("1"))]
    monkeypatch.setattr(market, "latest_asks", lambda instrument: asks)
    return asks


def place(client: APIClient, body: dict, key: str = "order-key-0001"):
    return client.post(reverse("orders"), body, format="json", HTTP_IDEMPOTENCY_KEY=key)


def usd(user: User, kind: str = AccountKind.AVAILABLE) -> Decimal:
    return ledger.balances(user)[Asset.USD][kind]


def test_limit_buy_reserves_cost_plus_fee_and_queues_the_order(client, owen):
    response = place(client, LIMIT_BUY)

    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "pending"
    assert order["reserved_amount"] == "40100.06000000"
    assert usd(owen, AccountKind.RESERVED) == Decimal("40100.06")
    event = OutboxEvent.objects.get()
    assert (event.topic, event.key, event.payload["type"]) == (
        "orders.commands",
        "kraken:BTC/USD",
        "order.placed",
    )
    assert event.payload["data"]["order_id"] == order["id"]
    assert event.payload["data"]["limit_price"] == "80000.10000000"


def test_market_buy_reserves_from_the_live_book(client, owen):
    body = {"symbol": "BTC/USD", "side": "buy", "type": "market", "quantity": "1.5"}

    response = place(client, body)

    assert response.status_code == 201
    assert usd(owen, AccountKind.RESERVED) == Decimal("153.90")  # 150.5 * 1.02 * 1.0025


def test_market_buy_without_live_prices_is_refused(client, monkeypatch):
    monkeypatch.setattr(market, "latest_asks", lambda instrument: None)

    response = place(
        client, {"symbol": "BTC/USD", "side": "buy", "type": "market", "quantity": "1"}
    )

    assert response.status_code == 503
    assert response.json()["code"] == "market_unavailable"


def test_market_buy_larger_than_the_book_is_refused(client):
    response = place(
        client, {"symbol": "BTC/USD", "side": "buy", "type": "market", "quantity": "3"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "insufficient_liquidity"


def test_sell_reserves_the_coins_being_sold(client, owen):
    ledger.transfer(
        "deposit",
        "gift",
        ledger.system_account(Asset.BTC, AccountKind.FUNDING),
        ledger.account(owen, Asset.BTC, AccountKind.AVAILABLE),
        Decimal("1"),
    )

    response = place(client, {**LIMIT_BUY, "side": "sell"})

    assert response.status_code == 201
    assert ledger.balances(owen)[Asset.BTC][AccountKind.RESERVED] == Decimal("0.5")


def test_rejected_order_leaves_no_trace(client):
    entries_before = Entry.objects.count()

    response = place(client, {**LIMIT_BUY, "side": "sell"})  # owen has no BTC

    assert response.status_code == 400
    assert response.json()["code"] == "insufficient_funds"
    assert not Order.objects.exists()
    assert not OutboxEvent.objects.exists()
    assert Entry.objects.count() == entries_before


def test_retry_with_the_same_key_returns_the_same_order(client, owen):
    first = place(client, LIMIT_BUY)
    retry = place(client, LIMIT_BUY)

    assert retry.status_code == 200
    assert retry["Idempotent-Replayed"] == "true"
    assert retry.json()["id"] == first.json()["id"]
    assert Order.objects.count() == 1
    assert OutboxEvent.objects.count() == 1
    assert usd(owen, AccountKind.RESERVED) == Decimal("40100.06")


def test_retrying_a_market_order_needs_no_live_prices(client, monkeypatch):
    body = {"symbol": "BTC/USD", "side": "buy", "type": "market", "quantity": "1"}
    first = place(client, body)
    monkeypatch.setattr(market, "latest_asks", lambda instrument: None)  # feed goes down

    retry = place(client, body)

    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]


def test_reusing_a_key_for_a_different_order_is_a_conflict(client):
    place(client, LIMIT_BUY)

    response = place(client, {**LIMIT_BUY, "quantity": "0.6"})

    assert response.status_code == 409
    assert Order.objects.count() == 1


def test_keys_are_per_user(client):
    other = logged_in(make_user("alice"))

    assert place(client, LIMIT_BUY).status_code == 201
    assert place(other, LIMIT_BUY).status_code == 201


@pytest.mark.parametrize("key", [None, "short", "has spaces in it", "x" * 65])
def test_a_valid_idempotency_key_is_required(client, key):
    headers = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}

    response = client.post(reverse("orders"), LIMIT_BUY, format="json", **headers)

    assert response.status_code == 400
    assert not Order.objects.exists()


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"quantity": "0.00001"}, "quantity"),  # below BTC's minimum
        ({"quantity": "0.000000001"}, "quantity"),  # more than 8 decimals
        ({"limit_price": "80000.15"}, "limit_price"),  # BTC/USD moves in steps of 0.1
        ({"limit_price": None}, "limit_price"),  # a limit order needs a price
        ({"type": "market"}, "limit_price"),  # a market order takes no price
        ({"symbol": "DOGE/USD"}, "symbol"),
    ],
)
def test_invalid_orders_are_rejected_with_the_field_named(client, change, field):
    response = place(client, {**LIMIT_BUY, **change})

    assert response.status_code == 400
    assert field in response.json()


def test_users_only_see_their_own_orders(client):
    place(client, LIMIT_BUY)
    alice = logged_in(make_user("alice"))

    assert len(client.get(reverse("orders")).json()) == 1
    assert alice.get(reverse("orders")).json() == []
    order_id = Order.objects.get().id
    assert alice.get(reverse("order", args=[order_id])).status_code == 404


def test_cancel_asks_the_engine_once(client):
    order_id = place(client, LIMIT_BUY).json()["id"]

    first = client.post(reverse("cancel-order", args=[order_id]))
    second = client.post(reverse("cancel-order", args=[order_id]))

    assert first.status_code == second.status_code == 202
    assert first.json()["cancel_requested"] is True
    types = [e.payload["type"] for e in OutboxEvent.objects.order_by("created_at")]
    assert types == ["order.placed", "order.cancel_requested"]


def test_cannot_cancel_a_finished_or_someone_elses_order(client):
    order_id = place(client, LIMIT_BUY).json()["id"]
    alice = logged_in(make_user("alice"))

    assert alice.post(reverse("cancel-order", args=[order_id])).status_code == 404
    Order.objects.filter(id=order_id).update(status=OrderStatus.FILLED)
    assert client.post(reverse("cancel-order", args=[order_id])).status_code == 409


def test_placing_an_order_needs_csrf_and_login(owen):
    anonymous = APIClient()
    assert place(anonymous, LIMIT_BUY).status_code == 403
    browser = APIClient(enforce_csrf_checks=True)
    browser.force_login(owen)
    assert place(browser, LIMIT_BUY).status_code == 403
