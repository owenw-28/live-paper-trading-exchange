"""Model-based property test: random operation sequences against a simple in-memory model."""

import itertools
from collections import defaultdict
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import transaction
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.ledger import services
from apps.ledger.models import ASSET_DECIMALS, AccountKind, Asset
from apps.ledger.services import InsufficientFunds

ASSETS = [Asset.USD, Asset.BTC]
USERS = 3
AVAILABLE, RESERVED = AccountKind.AVAILABLE, AccountKind.RESERVED

Key = tuple[int, str, str]  # (user index, asset, account kind)


@st.composite
def operations(draw) -> tuple[str, str, int, int, Decimal]:
    asset = draw(st.sampled_from(ASSETS))
    amount = Decimal(draw(st.integers(1, 10**9))).scaleb(-ASSET_DECIMALS[asset])
    kind = draw(st.sampled_from(["deposit", "reserve", "release", "pay"]))
    return kind, asset, draw(st.integers(0, USERS - 1)), draw(st.integers(0, USERS - 1)), amount


@pytest.mark.django_db
@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(operations(), max_size=25))
def test_ledger_matches_model_and_always_balances(ops):
    with transaction.atomic():
        check(ops)
        transaction.set_rollback(True)  # each example starts from an empty database


def check(ops: list[tuple[str, str, int, int, Decimal]]) -> None:
    users = [User.objects.create(username=f"u{i}") for i in range(USERS)]
    model: dict[Key, Decimal] = defaultdict(Decimal)
    references = (f"op:{n}" for n in itertools.count())

    for kind, asset, user, other, amount in ops:
        changes = expected_changes(kind, asset, user, other, amount)
        if all(model[key] + change >= 0 for key, change in changes.items()):
            perform(users, kind, asset, user, other, amount, next(references))
            for key, change in changes.items():
                model[key] += change
        else:
            with pytest.raises(InsufficientFunds):
                perform(users, kind, asset, user, other, amount, next(references))
        assert services.imbalance() == {}

    for i, user_obj in enumerate(users):
        actual = services.balances(user_obj)
        for asset in ASSETS:
            for account_kind in (AVAILABLE, RESERVED):
                expected = model[(i, asset, account_kind)]
                assert actual.get(asset, {}).get(account_kind, Decimal(0)) == expected
                assert expected >= 0


def expected_changes(kind: str, asset: str, user: int, other: int, amount: Decimal) -> dict:
    """How the model says each user account should change."""
    changes: dict[Key, Decimal] = defaultdict(Decimal)
    if kind == "deposit":
        changes[(user, asset, AVAILABLE)] += amount
    elif kind == "reserve":
        changes[(user, asset, AVAILABLE)] -= amount
        changes[(user, asset, RESERVED)] += amount
    elif kind == "release":
        changes[(user, asset, RESERVED)] -= amount
        changes[(user, asset, AVAILABLE)] += amount
    else:  # one user pays another (or themselves)
        changes[(user, asset, AVAILABLE)] -= amount
        changes[(other, asset, AVAILABLE)] += amount
    return changes


def perform(users, kind: str, asset: str, user: int, other: int, amount: Decimal, ref: str) -> None:
    """The same operation, done for real through the ledger."""
    if kind == "deposit":
        funding = services.system_account(asset, AccountKind.FUNDING)
        services.transfer(
            "deposit", ref, funding, services.account(users[user], asset, AVAILABLE), amount
        )
    elif kind == "reserve":
        services.reserve(users[user], asset, amount, ref)
    elif kind == "release":
        services.release(users[user], asset, amount, ref)
    else:
        payer = services.account(users[user], asset, AVAILABLE)
        payee = services.account(users[other], asset, AVAILABLE)
        services.transfer("fill", ref, payer, payee, amount)
