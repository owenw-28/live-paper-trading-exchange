from django.urls import path

from apps.trading import views

urlpatterns = [
    path("orders", views.OrdersView.as_view(), name="orders"),
    path("orders/<int:order_id>", views.OrderDetailView.as_view(), name="order"),
    path("orders/<int:order_id>/cancel", views.CancelOrderView.as_view(), name="cancel-order"),
]
