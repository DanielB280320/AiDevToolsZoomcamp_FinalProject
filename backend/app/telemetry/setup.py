"""OpenTelemetry providers for one app instance (spec §14).

The SDK providers always exist, so every request has a trace id for log correlation and
`Problem.request_id`. Exporters are attached only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
(OTLP over HTTP/protobuf, e.g. `http://otel-collector:4318`); without it nothing is exported and
no network call is made. Tests pass in-memory exporters instead.

Providers are per app and passed explicitly to the instrumentations rather than installed as
OTel globals, so several apps (tests) never share or fight over global state.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import (
    HTTPX2ClientInstrumentor,
    HTTPXClientInstrumentor,
)
from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer
from opentelemetry.instrumentation.sqlalchemy.version import __version__ as sqla_version
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span, Tracer

from app.config import Settings
from app.telemetry.metrics import FitwiseMetrics
from app.telemetry.privacy import METRIC_ATTRIBUTES, user_hash
from app.telemetry.spans import SanitizingSpanExporter

SERVICE_NAME: Final = "fitwise-backend"
INSTRUMENTATION_SCOPE: Final = "fitwise"
EngineName = Literal["progression", "meal_plan", "targets"]


@dataclass
class Telemetry:
    resource: Resource
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    tracer: Tracer
    metrics: FitwiseMetrics
    user_hash_salt: bytes = field(repr=False)

    def hash_user(self, user_id: Any) -> str:
        return user_hash(user_id, self.user_hash_salt)

    @contextmanager
    def engine_span(self, engine: EngineName) -> Iterator[Span]:
        """Custom span around a pure engine call: `engine.progression`, `engine.meal_plan`, ..."""
        with self.tracer.start_as_current_span(f"engine.{engine}") as span:
            yield span

    def shutdown(self) -> None:
        """Flush and stop exporters (app shutdown)."""
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def make_resource(settings: Settings) -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": settings.app_version,
            "deployment.environment.name": settings.app_env,
            "env": settings.app_env,
        }
    )


def build_telemetry(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_readers: tuple[MetricReader, ...] | None = None,
) -> Telemetry:
    """Providers for `settings`; `span_exporter`/`metric_readers` override OTLP (tests)."""
    resource = make_resource(settings)
    endpoint = settings.otel_exporter_otlp_endpoint

    processor: SpanProcessor | None = None
    if span_exporter is not None:
        processor = SimpleSpanProcessor(SanitizingSpanExporter(span_exporter))
    elif endpoint:
        processor = BatchSpanProcessor(
            SanitizingSpanExporter(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
    tracer_provider = TracerProvider(resource=resource)
    if processor is not None:
        tracer_provider.add_span_processor(processor)

    readers: tuple[MetricReader, ...] = ()
    if metric_readers is not None:
        readers = metric_readers
    elif endpoint:
        readers = (
            PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")),
        )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=readers,
        # One view for every instrument: labels outside the allow-list are dropped (§6.5).
        views=[View(instrument_name="*", attribute_keys=set(METRIC_ATTRIBUTES))],
    )

    meter = meter_provider.get_meter(INSTRUMENTATION_SCOPE, settings.app_version)
    return Telemetry(
        resource=resource,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        tracer=tracer_provider.get_tracer(INSTRUMENTATION_SCOPE, settings.app_version),
        metrics=FitwiseMetrics(meter),
        user_hash_salt=settings.user_hash_salt_bytes,
    )


def instrument_engine(engine: Any, telemetry: Telemetry) -> None:
    """Trace SQL on this engine only. Statements carry placeholders, never bound values."""
    meter = telemetry.meter_provider.get_meter("opentelemetry.instrumentation.sqlalchemy")
    EngineTracer(  # type: ignore[no-untyped-call]
        telemetry.tracer_provider.get_tracer(
            "opentelemetry.instrumentation.sqlalchemy", sqla_version
        ),
        engine,
        meter.create_up_down_counter(
            "db.client.connections.usage",
            unit="connections",
            description="Connections currently in the state given by the state attribute.",
        ),
        enable_commenter=False,
        enable_attribute_commenter=False,
    )


def instrument_http_client(client: Any, telemetry: Telemetry) -> None:
    """Trace an outgoing `httpx`/`httpx2` client (Open Food Facts); exported URLs have no query."""
    instrumentor = (
        HTTPX2ClientInstrumentor
        if type(client).__module__.startswith("httpx2")
        else HTTPXClientInstrumentor
    )
    instrumentor.instrument_client(
        client,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
    )


# Probes are polled by Docker/ALB every few seconds; tracing them would only add noise.
EXCLUDED_URLS: Final = "/api/v1/healthz,/api/v1/readyz"


def instrument_fastapi(app: Any, telemetry: Telemetry) -> None:
    """Server spans named by route template; no headers captured, no receive/send sub-spans.

    The library's own HTTP metrics are disabled: `RequestTelemetryMiddleware` records
    `http_server_duration` with exactly the labels route, method and status.
    """
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=NoOpMeterProvider(),
        excluded_urls=EXCLUDED_URLS,
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
        exclude_spans=["receive", "send"],
    )
