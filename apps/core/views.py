import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from opentelemetry import metrics

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)

readiness_failures = meter.create_counter(
    name="readiness.failures",
    description="Readiness checks that found a dependency unavailable",
)


@require_GET
def liveness(request):
    return JsonResponse({"status": "ok"})


@require_GET
def readiness(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.exception("Readiness check failed: database unreachable")
        readiness_failures.add(1, {"dependency": "database"})
        return JsonResponse(
            {"status": "unavailable", "checks": {"database": "error"}},
            status=503,
        )
    return JsonResponse({"status": "ok", "checks": {"database": "ok"}})
