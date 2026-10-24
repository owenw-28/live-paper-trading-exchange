from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Sum

from apps.ledger.models import (
    ASSET_DECIMALS,
    ZERO,
    Account,
    AccountKind,
    Asset,
    Entry,
    Transaction,
    TransactionKind,
)

STARTING_BALANCE = {Asset.USD: Decimal("100000.00")}


class LedgerError(Exception):
    """The transaction would break a ledger rule, so nothing was posted."""


class InsufficientFunds(LedgerError):
    pass


@dataclass(frozen=True)
class Leg:
    account: Account
    amount: Decimal


def account(owner: User | None, asset: str, kind: str) -> Account:
    found, _ = Account.objects.get_or_create(owner=owner, asset=asset, kind=kind)
    return found


def system_account(asset: str, kind: str) -> Account:
    return account(None, asset, kind)


def post(kind: str, reference: str, legs: list[Leg]) -> Transaction:
    """Post a balanced transaction atomically, or raise and post nothing.

    Idempotent: posting the same (kind, reference) again returns the original transaction.
    """
    _check_shape(legs)
    with transaction.atomic():
        existing = Transaction.objects.filter(kind=kind, reference=reference).first()
        if existing is not None:
            return existing
        # Lock every affected user account, always in id order so two transactions touching the
        # same accounts can't deadlock. Balances are checked only while holding the locks.
        user_accounts = sorted({leg.account.id for leg in legs if not leg.account.is_system})
        list(Account.objects.select_for_update().filter(id__in=user_accounts).order_by("id"))
        for account_id, change in _net_change_by_account(legs).items():
            if account_id in user_accounts and balance_of(account_id) + change < ZERO:
                raise InsufficientFunds(f"account {account_id} would go negative")
        try:
            with transaction.atomic():
                created = Transaction.objects.create(kind=kind, reference=reference)
        except IntegrityError:  # a concurrent post of the same cause won the race
            return Transaction.objects.get(kind=kind, reference=reference)
        Entry.objects.bulk_create(
            Entry(transaction=created, account=leg.account, amount=leg.amount) for leg in legs
        )
        return created


def transfer(
    kind: str, reference: str, source: Account, destination: Account, amount: Decimal
) -> Transaction:
    return post(kind, reference, [Leg(source, -amount), Leg(destination, amount)])


def fund_new_user(user: User) -> None:
    for asset, amount in STARTING_BALANCE.items():
        transfer(
            TransactionKind.DEPOSIT,
            f"signup:{user.id}:{asset}",
            system_account(asset, AccountKind.FUNDING),
            account(user, asset, AccountKind.AVAILABLE),
            amount,
        )


def reserve(user: User, asset: str, amount: Decimal, reference: str) -> Transaction:
    """Hold funds for an open order, so they can't be spent twice."""
    return transfer(
        TransactionKind.RESERVE,
        reference,
        account(user, asset, AccountKind.AVAILABLE),
        account(user, asset, AccountKind.RESERVED),
        amount,
    )


def release(user: User, asset: str, amount: Decimal, reference: str) -> Transaction:
    """Return held funds that an order no longer needs."""
    return transfer(
        TransactionKind.RELEASE,
        reference,
        account(user, asset, AccountKind.RESERVED),
        account(user, asset, AccountKind.AVAILABLE),
        amount,
    )


def balance_of(account_id: int) -> Decimal:
    total = Entry.objects.filter(account_id=account_id).aggregate(total=Sum("amount"))["total"]
    return total if total is not None else ZERO


def balances(user: User) -> dict[str, dict[str, Decimal]]:
    """{"USD": {"available": ..., "reserved": ...}, ...} for every asset the user has touched."""
    rows = (
        Entry.objects.filter(account__owner=user)
        .values("account__asset", "account__kind")
        .annotate(total=Sum("amount"))
    )
    result: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {AccountKind.AVAILABLE: ZERO, AccountKind.RESERVED: ZERO}
    )
    for row in rows:
        result[row["account__asset"]][row["account__kind"]] = row["total"]
    return dict(result)


def imbalance() -> dict[str, Decimal]:
    """Sum of every entry per asset. Must always be zero; anything else is a bug."""
    rows = Entry.objects.values("account__asset").annotate(total=Sum("amount"))
    return {row["account__asset"]: row["total"] for row in rows if row["total"] != ZERO}


def _check_shape(legs: list[Leg]) -> None:
    if len(legs) < 2:
        raise LedgerError("a transaction needs at least two legs")
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for leg in legs:
        if leg.amount == ZERO:
            raise LedgerError("legs must move a non-zero amount")
        places = ASSET_DECIMALS[Asset(leg.account.asset)]
        if leg.amount != leg.amount.quantize(Decimal(1).scaleb(-places)):
            raise LedgerError(f"{leg.account.asset} amounts have at most {places} decimal places")
        totals[leg.account.asset] += leg.amount
    unbalanced = {asset: total for asset, total in totals.items() if total != ZERO}
    if unbalanced:
        raise LedgerError(f"legs must sum to zero per asset, got {unbalanced}")


def _net_change_by_account(legs: list[Leg]) -> dict[int, Decimal]:
    changes: dict[int, Decimal] = defaultdict(Decimal)
    for leg in legs:
        changes[leg.account.id] += leg.amount
    return changes
