import pytest
from django.db import DatabaseError
from django.urls import reverse

from apps.core import views


def test_liveness_returns_ok(client):
    response = client.get(reverse("liveness"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_rejects_post(client):
    response = client.post(reverse("liveness"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_readiness_ok_when_database_reachable(client):
    response = client.get(reverse("readiness"))

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_readiness_returns_503_when_database_unreachable(client, monkeypatch):
    class BrokenConnection:
        def cursor(self):
            raise DatabaseError("connection refused")

    monkeypatch.setattr(views, "connection", BrokenConnection())

    response = client.get(reverse("readiness"))

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"
