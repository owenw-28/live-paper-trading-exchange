from django.contrib.auth.models import User
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ledger import services
from apps.ledger.models import ASSET_DECIMALS, AccountKind, Asset


class BalancesView(APIView):
    def get(self, request: Request) -> Response:
        assert isinstance(request.user, User)  # IsAuthenticated has already run
        result = []
        for asset, kinds in sorted(services.balances(request.user).items()):
            places = ASSET_DECIMALS[Asset(asset)]
            available, reserved = kinds[AccountKind.AVAILABLE], kinds[AccountKind.RESERVED]
            result.append(
                {
                    "asset": asset,
                    "available": f"{available:.{places}f}",
                    "reserved": f"{reserved:.{places}f}",
                    "total": f"{available + reserved:.{places}f}",
                }
            )
        return Response(result)
