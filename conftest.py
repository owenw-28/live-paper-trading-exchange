import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from config.telemetry import instrument_libraries

_span_exporter = InMemorySpanExporter()
_metric_reader = InMemoryMetricReader()


def pytest_configure(config):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
    trace.set_tracer_provider(provider)
    metrics.set_meter_provider(MeterProvider(metric_readers=[_metric_reader]))
    instrument_libraries()


@pytest.fixture
def finished_spans():
    _span_exporter.clear()
    return _span_exporter


@pytest.fixture
def histogram_counts():
    """A function returning {attributes: count} recorded into a histogram during this test."""
    before = _histogram_counts()

    def counts(name: str) -> dict[tuple, int]:
        start = before.get(name, {})
        now = _histogram_counts().get(name, {})
        return {
            attrs: n - start.get(attrs, 0) for attrs, n in now.items() if n > start.get(attrs, 0)
        }

    return counts


def _histogram_counts() -> dict[str, dict[tuple, int]]:
    result: dict[str, dict[tuple, int]] = {}
    data = _metric_reader.get_metrics_data()
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                for point in getattr(metric.data, "data_points", []):
                    if hasattr(point, "bucket_counts"):
                        attrs = tuple(sorted(point.attributes.items()))
                        result.setdefault(metric.name, {})[attrs] = point.count
    return result
