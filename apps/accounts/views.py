from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import CredentialsSerializer, SignUpSerializer, UserSerializer
from apps.ledger.services import fund_new_user


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """Sets the CSRF cookie, which the browser app sends back as a header on every write."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="post")
class SignUpView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "signup"

    def post(self, request: Request) -> Response:
        serializer = SignUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():  # a user always exists together with their starting balance
                user = User.objects.create_user(
                    username=serializer.validated_data["username"],
                    password=serializer.validated_data["password"],
                )
                fund_new_user(user)
        except IntegrityError:  # someone took the name between our check and the insert
            return Response(
                {"username": ["That username is taken."]}, status=status.HTTP_400_BAD_REQUEST
            )
        login(request._request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="post")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request: Request) -> Response:
        serializer = CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request._request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": "Incorrect username or password."}, status=status.HTTP_400_BAD_REQUEST
            )
        login(request._request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)
