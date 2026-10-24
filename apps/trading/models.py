from django.conf import settings
from django.db import models

from apps.ledger.models import Asset
from apps.trading.instruments import INSTRUMENTS


class Side(models.TextChoices):
    BUY = "buy"
    SELL = "sell"


class OrderType(models.TextChoices):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(models.TextChoices):
    PENDING = "pending"  # accepted and funds reserved; the fill engine hasn't seen it yet
    OPEN = "open"  # a limit order resting until the market trades through its price
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


FINAL_STATUSES = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}


class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=64)
    symbol = models.CharField(max_length=16, choices=[(s, s) for s in INSTRUMENTS])
    side = models.CharField(max_length=4, choices=Side.choices)
    order_type = models.CharField(max_length=6, choices=OrderType.choices)
    quantity = models.DecimalField(max_digits=24, decimal_places=8)
    limit_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )
    filled_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    reserved_asset = models.CharField(max_length=8, choices=Asset.choices)
    reserved_amount = models.DecimalField(max_digits=24, decimal_places=8)
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "idempotency_key"], name="one_order_per_key"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="positive_quantity"),
            models.CheckConstraint(
                condition=models.Q(order_type=OrderType.LIMIT, limit_price__gt=0)
                | models.Q(order_type=OrderType.MARKET, limit_price__isnull=True),
                name="limit_orders_have_a_price",
            ),
        ]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        price = f" @ {self.limit_price}" if self.limit_price is not None else ""
        return f"#{self.id} {self.side} {self.quantity} {self.symbol}{price} ({self.status})"
