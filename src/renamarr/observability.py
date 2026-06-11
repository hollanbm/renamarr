import os
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from typing import Literal, Protocol, TypeAlias

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.metrics import Counter
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

AttributeValue: TypeAlias = str | bool | int | float
SpanAttributes: TypeAlias = Mapping[str, AttributeValue]
TraceContext: TypeAlias = dict[str, str]
ServiceName: TypeAlias = Literal["sonarr", "radarr"]
OperationName: TypeAlias = Literal["rename", "folder_rename"]
OperationResult: TypeAlias = Literal["accepted", "failed"]
JobResult: TypeAlias = Literal["success", "failed"]

OTEL_ENABLED_ENV_VAR = "RENAMARR_OTEL_ENABLED"
DEFAULT_SERVICE_NAME = "renamarr"


class Observability(Protocol):
    """Application telemetry interface."""

    def start_span(
        self, name: str, attributes: SpanAttributes | None = None
    ) -> AbstractContextManager[object]:
        """Start a trace span."""

    def record_operation_items(
        self,
        service: ServiceName,
        operation: OperationName,
        name: str,
        result: OperationResult,
        item_count: int,
    ) -> None:
        """Record accepted or failed rename operation items."""

    def record_job(
        self,
        service: ServiceName,
        name: str,
        job: str,
        result: JobResult,
        duration_seconds: float,
    ) -> None:
        """Record a completed scheduled job."""

    def force_flush(self) -> None:
        """Flush pending telemetry."""

    def shutdown(self) -> None:
        """Flush telemetry and release resources."""


class DisabledObservability:
    """No-op telemetry implementation."""

    def start_span(
        self, name: str, attributes: SpanAttributes | None = None
    ) -> AbstractContextManager[object]:
        """Return a no-op span context."""
        return nullcontext()

    def record_operation_items(
        self,
        service: ServiceName,
        operation: OperationName,
        name: str,
        result: OperationResult,
        item_count: int,
    ) -> None:
        """Ignore operation metrics."""

    def record_job(
        self,
        service: ServiceName,
        name: str,
        job: str,
        result: JobResult,
        duration_seconds: float,
    ) -> None:
        """Ignore job metrics."""

    def force_flush(self) -> None:
        """Skip flushing."""

    def shutdown(self) -> None:
        """Skip shutdown."""


class OpenTelemetryObservability:
    """OpenTelemetry-backed observability implementation."""

    def __init__(
        self,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
        requests_instrumentor: RequestsInstrumentor,
    ) -> None:
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._requests_instrumentor = requests_instrumentor
        self._tracer = tracer_provider.get_tracer(DEFAULT_SERVICE_NAME)
        meter = meter_provider.get_meter(DEFAULT_SERVICE_NAME)
        self._operation_counters: dict[tuple[ServiceName, OperationName], Counter] = {
            ("sonarr", "rename"): meter.create_counter(
                "renamarr.sonarr.rename.items",
                unit="{item}",
                description="Sonarr episode file rename items accepted or failed.",
            ),
            ("sonarr", "folder_rename"): meter.create_counter(
                "renamarr.sonarr.folder_rename.items",
                unit="{item}",
                description="Sonarr folder rename items accepted or failed.",
            ),
            ("radarr", "rename"): meter.create_counter(
                "renamarr.radarr.rename.items",
                unit="{item}",
                description="Radarr movie file rename items accepted or failed.",
            ),
            ("radarr", "folder_rename"): meter.create_counter(
                "renamarr.radarr.folder_rename.items",
                unit="{item}",
                description="Radarr folder rename items accepted or failed.",
            ),
        }
        self._job_runs = meter.create_counter(
            "renamarr.job.runs",
            unit="{run}",
            description="Renamarr job runs.",
        )
        self._job_duration = meter.create_histogram(
            "renamarr.job.duration",
            unit="s",
            description="Renamarr job duration.",
        )

    @classmethod
    def build(cls) -> "OpenTelemetryObservability":
        """Build OpenTelemetry providers from standard OTEL environment variables."""
        resource = Resource.create(
            {"service.name": os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)}
        )
        tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
            shutdown_on_exit=False,
        )

        requests_instrumentor = RequestsInstrumentor()
        requests_instrumentor.instrument(tracer_provider=tracer_provider)
        return cls(tracer_provider, meter_provider, requests_instrumentor)

    def start_span(
        self, name: str, attributes: SpanAttributes | None = None
    ) -> AbstractContextManager[object]:
        """Start an OpenTelemetry span."""
        return self._tracer.start_as_current_span(name, attributes=attributes)

    def record_operation_items(
        self,
        service: ServiceName,
        operation: OperationName,
        name: str,
        result: OperationResult,
        item_count: int,
    ) -> None:
        """Record accepted or failed rename operation items."""
        self._operation_counters[(service, operation)].add(
            item_count,
            attributes={"name": name, "result": result},
        )

    def record_job(
        self,
        service: ServiceName,
        name: str,
        job: str,
        result: JobResult,
        duration_seconds: float,
    ) -> None:
        """Record a completed scheduled job."""
        attributes = {
            "service": service,
            "name": name,
            "job": job,
            "result": result,
        }
        self._job_runs.add(1, attributes=attributes)
        self._job_duration.record(duration_seconds, attributes=attributes)

    def force_flush(self) -> None:
        """Flush pending spans and metrics."""
        self._tracer_provider.force_flush()
        self._meter_provider.force_flush()

    def shutdown(self) -> None:
        """Flush telemetry, uninstrument requests, and stop providers."""
        self.force_flush()
        self._requests_instrumentor.uninstrument()
        self._tracer_provider.shutdown()
        self._meter_provider.shutdown()


def is_otel_enabled() -> bool:
    """Return whether Renamarr OpenTelemetry instrumentation is enabled."""
    return os.getenv(OTEL_ENABLED_ENV_VAR, "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_log_trace_context() -> TraceContext:
    """Return the active trace context for Loguru correlation fields."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {"trace_id": "", "span_id": ""}
    return {
        "trace_id": f"{span_context.trace_id:032x}",
        "span_id": f"{span_context.span_id:016x}",
    }


def enrich_log_record_with_trace(record: dict[str, object]) -> None:
    """Add active OpenTelemetry trace identifiers to a Loguru record."""
    extra = record.get("extra")
    if isinstance(extra, dict):
        extra.update(get_log_trace_context())


_observability: Observability = DisabledObservability()


def configure_observability() -> Observability:
    """Configure the process-wide Renamarr observability implementation."""
    global _observability
    if is_otel_enabled():
        _observability = OpenTelemetryObservability.build()
    else:
        _observability = DisabledObservability()
    return _observability


def get_observability() -> Observability:
    """Return the configured Renamarr observability implementation."""
    return _observability
