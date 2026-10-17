import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from config.telemetry import instrument_libraries

_span_exporter = InMemorySpanExporter()


def pytest_configure(config):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
    trace.set_tracer_provider(provider)
    instrument_libraries()


@pytest.fixture
def finished_spans():
    _span_exporter.clear()
    return _span_exporter
