from decimal import Decimal

from rest_framework import serializers

from apps.trading.instruments import INSTRUMENTS
from apps.trading.models import Order, OrderType, Side


class OrderRequestSerializer(serializers.Serializer):
    symbol = serializers.ChoiceField(choices=list(INSTRUMENTS))
    side = serializers.ChoiceField(choices=Side.choices)
    type = serializers.ChoiceField(choices=OrderType.choices)
    quantity = serializers.DecimalField(max_digits=24, decimal_places=8)
    limit_price = serializers.DecimalField(
        max_digits=24, decimal_places=8, required=False, allow_null=True
    )

    def validate(self, attrs: dict) -> dict:
        instrument = INSTRUMENTS[attrs["symbol"]]
        quantity: Decimal = attrs["quantity"]
        price: Decimal | None = attrs.get("limit_price")
        errors: dict[str, str] = {}
        if quantity < instrument.min_quantity:
            errors["quantity"] = f"The minimum is {instrument.min_quantity}."
        elif quantity % instrument.quantity_step:
            errors["quantity"] = f"Use steps of {instrument.quantity_step}."
        if attrs["type"] == OrderType.LIMIT:
            if price is None:
                errors["limit_price"] = "A limit order needs a price."
            elif price <= 0 or price % instrument.price_tick:
                errors["limit_price"] = f"Use a positive multiple of {instrument.price_tick}."
        elif price is not None:
            errors["limit_price"] = "A market order takes no price."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class OrderSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="order_type")

    class Meta:
        model = Order
        fields = [
            "id",
            "symbol",
            "side",
            "type",
            "quantity",
            "limit_price",
            "status",
            "filled_quantity",
            "average_price",
            "quote_amount",
            "fee",
            "reject_reason",
            "reserved_asset",
            "reserved_amount",
            "cancel_requested",
            "created_at",
            "settled_at",
        ]
