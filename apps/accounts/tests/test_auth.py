import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

STRONG = "correct-horse-battery-staple"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def sign_up(client: APIClient, username: str = "owen", password: str = STRONG):
    return client.post(reverse("signup"), {"username": username, "password": password})


@pytest.mark.django_db
def test_sign_up_creates_user_and_logs_in(client):
    response = sign_up(client)

    assert response.status_code == 201
    assert response.json()["username"] == "owen"
    assert client.get(reverse("me")).json()["username"] == "owen"


@pytest.mark.django_db
def test_password_is_stored_hashed(client):
    sign_up(client)

    stored = User.objects.get(username="owen").password
    assert STRONG not in stored
    assert stored.startswith(("pbkdf2_", "argon2", "scrypt"))


@pytest.mark.django_db
def test_username_is_unique_ignoring_case(client):
    sign_up(client, "owen")

    response = sign_up(APIClient(), "OWEN")

    assert response.status_code == 400
    assert "username" in response.json()


@pytest.mark.django_db
@pytest.mark.parametrize("password", ["short", "password123", "12345678"])
def test_weak_passwords_are_rejected(client, password):
    response = sign_up(client, "owen", password)

    assert response.status_code == 400
    assert "password" in response.json()
    assert not User.objects.exists()


@pytest.mark.django_db
def test_login_and_logout(client):
    User.objects.create_user("owen", password=STRONG)

    assert (
        client.post(reverse("login"), {"username": "owen", "password": STRONG}).status_code == 200
    )
    assert client.get(reverse("me")).status_code == 200
    assert client.post(reverse("logout")).status_code == 204
    assert client.get(reverse("me")).status_code == 403


@pytest.mark.django_db
def test_wrong_password_gives_one_generic_message(client):
    User.objects.create_user("owen", password=STRONG)

    wrong_password = client.post(reverse("login"), {"username": "owen", "password": "nope"})
    no_such_user = client.post(reverse("login"), {"username": "nobody", "password": "nope"})

    assert wrong_password.status_code == no_such_user.status_code == 400
    assert wrong_password.json() == no_such_user.json()


@pytest.mark.django_db
def test_me_requires_login(client):
    assert client.get(reverse("me")).status_code == 403


@pytest.mark.django_db
def test_login_requires_csrf_token():
    User.objects.create_user("owen", password=STRONG)
    browser = APIClient(enforce_csrf_checks=True)
    credentials = {"username": "owen", "password": STRONG}

    without_token = browser.post(reverse("login"), credentials)
    browser.get(reverse("csrf"))
    token = browser.cookies["csrftoken"].value
    with_token = browser.post(reverse("login"), credentials, HTTP_X_CSRFTOKEN=token)

    assert without_token.status_code == 403
    assert with_token.status_code == 200


@pytest.mark.django_db
def test_login_is_rate_limited_per_client(client):
    User.objects.create_user("owen", password=STRONG)
    attempt = {"username": "owen", "password": "wrong"}

    codes = [
        client.post(reverse("login"), attempt, HTTP_X_FORWARDED_FOR="203.0.113.7").status_code
        for _ in range(11)
    ]
    other_client = client.post(reverse("login"), attempt, HTTP_X_FORWARDED_FOR="198.51.100.9")

    assert codes[:10] == [400] * 10
    assert codes[10] == 429
    assert other_client.status_code == 400


@pytest.mark.django_db
def test_rate_limit_cannot_be_dodged_by_faking_forwarded_for(client):
    attempt = {"username": "owen", "password": "wrong"}

    codes = [
        client.post(
            reverse("login"), attempt, HTTP_X_FORWARDED_FOR=f"10.0.0.{n}, 203.0.113.7"
        ).status_code
        for n in range(11)
    ]

    assert codes[10] == 429
