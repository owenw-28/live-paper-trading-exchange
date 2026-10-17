import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient
from django.urls import reverse


@pytest.mark.django_db
def test_readiness_request_is_traced_with_database_child_span(finished_spans):
    response = async_to_sync(AsyncClient().get)(reverse("readiness"))

    assert response.status_code == 200
    spans = finished_spans.get_finished_spans()
    request_spans = [s for s in spans if s.name == "GET readyz"]
    assert len(request_spans) == 1, f"no request span; got {[s.name for s in spans]}"
    request_span = request_spans[0]
    db_children = [
        s
        for s in spans
        if s.name == "SELECT"
        and s.parent is not None
        and s.parent.span_id == request_span.context.span_id
    ]
    assert len(db_children) == 1
