import re

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.trading import services
from apps.trading.models import Order
from apps.trading.serializers import OrderRequestSerializer, OrderSerializer
from apps.trading.services import IdempotencyConflict, OrderRejected, OrderRequest

IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
REJECTION_STATUS = {"market_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE}


def _user(request: Request) -> User:
    assert isinstance(request.user, User)  # IsAuthenticated has already run
    return request.user


class OrdersView(APIView):
    throttle_scope = "orders"

    def get(self, request: Request) -> Response:
        orders = Order.objects.filter(user=_user(request)).order_by("-created_at")
        if "status" in request.query_params:
            orders = orders.filter(status=request.query_params["status"])
        return Response(OrderSerializer(orders[:100], many=True).data)

    def post(self, request: Request) -> Response:
        key = request.headers.get("Idempotency-Key", "")
        if not IDEMPOTENCY_KEY.fullmatch(key):
            return Response(
                {"detail": "Send an Idempotency-Key header of 8-64 letters, digits, - or _."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = OrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order_request = OrderRequest(
            data["symbol"], data["side"], data["type"], data["quantity"], data.get("limit_price")
        )
        try:
            order, created = services.place_order(_user(request), order_request, key)
        except IdempotencyConflict:
            return Response(
                {"detail": "This Idempotency-Key was already used for a different order."},
                status=status.HTTP_409_CONFLICT,
            )
        except OrderRejected as rejection:
            return Response(
                {"detail": str(rejection), "code": rejection.code},
                status=REJECTION_STATUS.get(rejection.code, status.HTTP_400_BAD_REQUEST),
            )
        response = Response(
            OrderSerializer(order).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
        if not created:
            response["Idempotent-Replayed"] = "true"
        return response


class OrderDetailView(APIView):
    def get(self, request: Request, order_id: int) -> Response:
        order = Order.objects.filter(user=_user(request), id=order_id).first()
        if order is None:  # 404, not 403: don't reveal that someone else's order exists
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(OrderSerializer(order).data)


class CancelOrderView(APIView):
    throttle_scope = "orders"

    def post(self, request: Request, order_id: int) -> Response:
        try:
            order = services.cancel_order(_user(request), order_id)
        except Order.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except OrderRejected as rejection:
            return Response(
                {"detail": str(rejection), "code": rejection.code}, status=status.HTTP_409_CONFLICT
            )
        return Response(OrderSerializer(order).data, status=status.HTTP_202_ACCEPTED)
