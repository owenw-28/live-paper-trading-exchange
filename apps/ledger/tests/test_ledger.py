from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.ledger import services
from apps.ledger.models import Account, AccountKind, Asset, Entry, Transaction
from apps.ledger.services import InsufficientFunds, LedgerError, Leg

pytestmark = pytest.mark.django_db


@pytest.fixture
def owen() -> User:
    user = User.objects.create_user("owen", password="correct-horse-battery-staple")
    services.fund_new_user(user)
    return user


def available(user: User, asset: str = Asset.USD) -> Decimal:
    return services.balances(user).get(asset, {}).get(AccountKind.AVAILABLE, Decimal(0))


def test_new_user_is_funded_once(owen):
    services.fund_new_user(owen)  # e.g. a retried sign-up

    assert available(owen) == Decimal("100000.00")
    assert services.imbalance() == {}


def test_reserve_and_release_move_funds_within_the_user(owen):
    services.reserve(owen, Asset.USD, Decimal("250.00"), "order:1")
    services.release(owen, Asset.USD, Decimal("100.00"), "order:1")

    usd = services.balances(owen)[Asset.USD]
    assert usd[AccountKind.AVAILABLE] == Decimal("99850.00")
    assert usd[AccountKind.RESERVED] == Decimal("150.00")
    assert services.imbalance() == {}


def test_cannot_spend_more_than_available_and_nothing_is_posted(owen):
    before = Entry.objects.count()

    with pytest.raises(InsufficientFunds):
        services.reserve(owen, Asset.USD, Decimal("100000.01"), "order:1")

    assert Entry.objects.count() == before


def test_posting_the_same_cause_twice_moves_money_once(owen):
    first = services.reserve(owen, Asset.USD, Decimal("10.00"), "order:1")
    second = services.reserve(owen, Asset.USD, Decimal("10.00"), "order:1")

    assert first.id == second.id
    assert available(owen) == Decimal("99990.00")


def test_retrying_a_large_reservation_returns_the_original_not_insufficient_funds(owen):
    first = services.reserve(owen, Asset.USD, Decimal("60000.00"), "order:1")

    retry = services.reserve(owen, Asset.USD, Decimal("60000.00"), "order:1")

    assert retry.id == first.id
    assert available(owen) == Decimal("40000.00")


@pytest.mark.parametrize(
    ("amounts", "message"),
    [
        (["1.00"], "at least two legs"),
        (["1.00", "-0.99"], "sum to zero"),
        (["0.001", "-0.001"], "decimal places"),
        (["0", "0"], "non-zero"),
    ],
)
def test_malformed_transactions_are_rejected(owen, amounts, message):
    usd = services.account(owen, Asset.USD, AccountKind.AVAILABLE)
    other = services.system_account(Asset.USD, AccountKind.MARKET)
    legs = [Leg(usd if i == 0 else other, Decimal(a)) for i, a in enumerate(amounts)]

    with pytest.raises(LedgerError, match=message):
        services.post("deposit", "bad", legs)

    assert not Transaction.objects.filter(reference="bad").exists()


def test_btc_uses_satoshi_precision(owen):
    market = services.system_account(Asset.BTC, AccountKind.MARKET)
    wallet = services.account(owen, Asset.BTC, AccountKind.AVAILABLE)

    services.transfer("fill", "fill:1", market, wallet, Decimal("0.00000001"))

    assert available(owen, Asset.BTC) == Decimal("0.00000001")


def test_system_accounts_may_go_negative(owen):
    funding = services.system_account(Asset.USD, AccountKind.FUNDING)

    assert services.balance_of(funding.id) == Decimal("-100000.00")


def test_database_rejects_zero_entries(owen):
    tx = Transaction.objects.create(kind="deposit", reference="raw")
    account = services.account(owen, Asset.USD, AccountKind.AVAILABLE)

    with pytest.raises(IntegrityError), transaction.atomic():
        Entry.objects.create(transaction=tx, account=account, amount=Decimal(0))


def test_database_rejects_a_user_owning_a_system_account(owen):
    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.create(owner=owen, asset=Asset.USD, kind=AccountKind.FEES)


def test_sign_up_funds_the_account_and_balances_are_exact_strings():
    client = APIClient()
    client.post(reverse("signup"), {"username": "owen", "password": "correct-horse-battery"})

    response = client.get(reverse("balances"))

    assert response.json() == [
        {"asset": "USD", "available": "100000.00", "reserved": "0.00", "total": "100000.00"}
    ]


def test_failed_funding_leaves_no_half_created_user(monkeypatch):
    def broken(user):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr("apps.accounts.views.fund_new_user", broken)
    client = APIClient(raise_request_exception=False)

    response = client.post(reverse("signup"), {"username": "owen", "password": "correct-horse-1"})

    assert response.status_code == 500
    assert not User.objects.filter(username="owen").exists()


def test_balances_require_login():
    assert APIClient().get(reverse("balances")).status_code == 403
