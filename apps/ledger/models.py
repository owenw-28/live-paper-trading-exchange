from decimal import Decimal

from django.conf import settings
from django.db import models


class Asset(models.TextChoices):
    USD = "USD"
    BTC = "BTC"
    ETH = "ETH"


# Smallest unit each asset is recorded in: cents for dollars, satoshis for bitcoin.
ASSET_DECIMALS = {Asset.USD: 2, Asset.BTC: 8, Asset.ETH: 8}


class AccountKind(models.TextChoices):
    AVAILABLE = "available"  # a user's spendable funds
    RESERVED = "reserved"  # a user's funds held for open orders
    FUNDING = "funding"  # the exchange: source of starting balances
    MARKET = "market"  # the exchange: the other side of every fill
    FEES = "fees"  # the exchange: fees collected


USER_KINDS = {AccountKind.AVAILABLE, AccountKind.RESERVED}
SYSTEM_KINDS = {AccountKind.FUNDING, AccountKind.MARKET, AccountKind.FEES}


class Account(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    asset = models.CharField(max_length=8, choices=Asset.choices)
    kind = models.CharField(max_length=16, choices=AccountKind.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "asset", "kind"],
                nulls_distinct=False,
                name="one_account_per_owner_asset_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(owner__isnull=True, kind__in=SYSTEM_KINDS)
                | models.Q(owner__isnull=False, kind__in=USER_KINDS),
                name="system_accounts_have_no_owner",
            ),
        ]

    def __str__(self) -> str:
        owner = self.owner_id if self.owner_id is not None else "exchange"
        return f"{owner}:{self.kind}:{self.asset}"

    @property
    def is_system(self) -> bool:
        return self.kind in SYSTEM_KINDS


class TransactionKind(models.TextChoices):
    DEPOSIT = "deposit"
    RESERVE = "reserve"
    RELEASE = "release"
    FILL = "fill"


class Transaction(models.Model):
    kind = models.CharField(max_length=16, choices=TransactionKind.choices)
    # What caused this transaction, e.g. "signup:42" or "order:7". With `kind`, unique: posting
    # the same thing twice returns the first transaction instead of moving money twice.
    reference = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "reference"], name="one_transaction_per_cause")
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.reference}"


class Entry(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    amount = models.DecimalField(max_digits=24, decimal_places=8)  # + into the account, - out

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="no_zero_entries")
        ]
        indexes = [models.Index(fields=["account"])]

    def __str__(self) -> str:
        return f"{self.account} {self.amount:+}"


ZERO = Decimal(0)
