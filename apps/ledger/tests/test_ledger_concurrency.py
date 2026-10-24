import threading
import time
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import connection

from apps.ledger import services
from apps.ledger.models import AccountKind, Asset
from apps.ledger.services import InsufficientFunds


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_reservations_cannot_spend_the_same_dollars(monkeypatch):
    user = User.objects.create_user("owen")
    services.fund_new_user(user)
    real_balance_of = services.balance_of

    def slow_balance_of(account_id):
        balance = real_balance_of(account_id)
        time.sleep(0.2)  # widen the window between checking and writing
        return balance

    monkeypatch.setattr(services, "balance_of", slow_balance_of)
    start = threading.Barrier(2)
    outcomes: list[str] = []

    def reserve(order: int) -> None:
        start.wait()
        try:
            services.reserve(user, Asset.USD, Decimal("60000.00"), f"order:{order}")
            outcomes.append("reserved")
        except InsufficientFunds:
            outcomes.append("insufficient")
        finally:
            connection.close()

    threads = [threading.Thread(target=reserve, args=(n,)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["insufficient", "reserved"]
    usd = services.balances(user)[Asset.USD]
    assert usd[AccountKind.AVAILABLE] == Decimal("40000.00")
    assert usd[AccountKind.RESERVED] == Decimal("60000.00")
