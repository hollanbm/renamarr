import os
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from typing import Protocol, TypeAlias

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from renamarr.otel.arr_command_result import ArrCommandResult
from renamarr.otel.job_result import JobResult
from renamarr.otel.operation_name import OperationName
from renamarr.otel.operation_result import OperationResult
from renamarr.otel.service_name import ServiceName

AttributeValue: TypeAlias = str | bool | int | float
SpanAttributes: TypeAlias = Mapping[str, AttributeValue]
TraceContext: TypeAlias = dict[str, str]


OTEL_ENABLED_ENV_VAR = "RENAMARR_OTEL_ENABLED"
DEFAULT_SERVICE_NAME = "renamarr"
ARR_COMMAND_DURATION_HISTOGRAM_NAME = "renamarr.arr.command.duration"
ARR_COMMAND_DURATION_SECONDS_BUCKETS = (
    1.0,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    180.0,
    240.0,
    300.0,
)


class Observability(Protocol):
    """Application telemetry interface."""

    def start_span(
        self, name: str, attributes: SpanAttributes | None = None
    ) -> AbstractContextManager[object]:
        """Start a trace span."""

    def record_operation_items(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        result: OperationResult,
        item_count: int,
    ) -> None:
        """Record rename operation items."""

    def record_operation_candidate_items(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        item_count: int,
    ) -> None:
        """Record items selected as rename candidates."""

    def record_operation_run(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        result: OperationResult,
    ) -> None:
        """Record a completed rename operation run."""

    def record_arr_command(
        self,
        service: ServiceName,
        name: str,
        command: str,
        result: ArrCommandResult,
        duration_seconds: float,
    ) -> None:
        """Record a completed Sonarr or Radarr command."""

    def record_job_started(
        self,
        service: ServiceName,
        name: str,
        job: str,
        timestamp_seconds: float,
    ) -> None:
        """Record when a scheduled job started."""

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
        name: str,
        operation: OperationName,
        result: OperationResult,
        item_count: int,
    ) -> None:
        """Ignore operation metrics."""

    def record_operation_candidate_items(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        item_count: int,
    ) -> None:
        """Ignore operation metrics."""

    def record_operation_run(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        result: OperationResult,
    ) -> None:
        """Ignore operation metrics."""

    def record_arr_command(
        self,
        service: ServiceName,
        name: str,
        command: str,
        result: ArrCommandResult,
        duration_seconds: float,
    ) -> None:
        """Ignore command metrics."""

    def record_job_started(
        self,
        service: ServiceName,
        name: str,
        job: str,
        timestamp_seconds: float,
    ) -> None:
        """Ignore job metrics."""

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
        self._job_last_started = meter.create_gauge(
            "renamarr.job.last_started",
            unit="s",
            description="Unix timestamp of the latest Renamarr job start.",
        )
        self._job_last_completed = meter.create_gauge(
            "renamarr.job.last_completed",
            unit="s",
            description="Unix timestamp of the latest Renamarr job completion.",
        )
        self._job_last_success = meter.create_gauge(
            "renamarr.job.last_success",
            unit="s",
            description="Unix timestamp of the latest successful Renamarr job.",
        )
        self._operation_runs = meter.create_counter(
            "renamarr.operation.runs",
            unit="{run}",
            description="Renamarr rename operation runs.",
        )
        self._operation_items = meter.create_counter(
            "renamarr.operation.items",
            unit="{item}",
            description="Renamarr rename operation items.",
        )
        self._operation_candidate_items = meter.create_counter(
            "renamarr.operation.candidate.items",
            unit="{item}",
            description="Items selected as Renamarr rename candidates.",
        )
        self._arr_command_runs = meter.create_counter(
            "renamarr.arr.command.runs",
            unit="{run}",
            description="Sonarr and Radarr commands observed by Renamarr.",
        )
        self._arr_command_duration = meter.create_histogram(
            ARR_COMMAND_DURATION_HISTOGRAM_NAME,
            unit="s",
            description="Sonarr and Radarr command duration observed by Renamarr.",
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
            views=[
                View(
                    instrument_name=ARR_COMMAND_DURATION_HISTOGRAM_NAME,
                    aggregation=ExplicitBucketHistogramAggregation(
                        boundaries=ARR_COMMAND_DURATION_SECONDS_BUCKETS
                    ),
                )
            ],
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
        name: str,
        operation: OperationName,
        result: OperationResult,
        item_count: int,
    ) -> None:
        """Record rename operation items."""
        self._operation_items.add(
            item_count,
            attributes={
                "service": service,
                "name": name,
                "operation": operation,
                "result": result,
            },
        )

    def record_operation_candidate_items(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        item_count: int,
    ) -> None:
        """Record items selected as rename candidates."""
        self._operation_candidate_items.add(
            item_count,
            attributes={"service": service, "name": name, "operation": operation},
        )

    def record_operation_run(
        self,
        service: ServiceName,
        name: str,
        operation: OperationName,
        result: OperationResult,
    ) -> None:
        """Record a completed rename operation run."""
        self._operation_runs.add(
            1,
            attributes={
                "service": service,
                "name": name,
                "operation": operation,
                "result": result,
            },
        )

    def record_arr_command(
        self,
        service: ServiceName,
        name: str,
        command: str,
        result: ArrCommandResult,
        duration_seconds: float,
    ) -> None:
        """Record a completed Sonarr or Radarr command."""
        attributes = {
            "service": service,
            "name": name,
            "command": command,
            "result": result,
        }
        self._arr_command_runs.add(1, attributes=attributes)
        self._arr_command_duration.record(duration_seconds, attributes=attributes)

    def record_job_started(
        self,
        service: ServiceName,
        name: str,
        job: str,
        timestamp_seconds: float,
    ) -> None:
        """Record when a scheduled job started."""
        self._job_last_started.set(
            timestamp_seconds,
            attributes={"service": service, "name": name, "job": job},
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
        timestamp_seconds = time.time()
        timestamp_attributes = {"service": service, "name": name, "job": job}
        self._job_last_completed.set(
            timestamp_seconds,
            attributes=timestamp_attributes,
        )
        if result == JobResult.SUCCESS:
            self._job_last_success.set(
                timestamp_seconds,
                attributes=timestamp_attributes,
            )

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
