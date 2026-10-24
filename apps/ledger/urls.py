from django.urls import path

from apps.ledger import views

urlpatterns = [path("balances", views.BalancesView.as_view(), name="balances")]
