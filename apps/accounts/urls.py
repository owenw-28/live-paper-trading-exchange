from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("csrf", views.CsrfView.as_view(), name="csrf"),
    path("signup", views.SignUpView.as_view(), name="signup"),
    path("login", views.LoginView.as_view(), name="login"),
    path("logout", views.LogoutView.as_view(), name="logout"),
    path("me", views.MeView.as_view(), name="me"),
]
