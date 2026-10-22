import json
import os
import re
import time
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from types import MappingProxyType

from loguru import logger
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.instrumentation.urllib3 import RequestInfo, URLLib3Instrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Status, StatusCode
from opentelemetry.util.types import AnyValue, Attributes

from renamarr.models.scan import ScanResult

_CONTEXT: ContextVar[Mapping[str, str]] = ContextVar(
    "renamarr_telemetry", default=MappingProxyType({})
)
_CREDENTIAL = re.compile(
    r"(?i)(api[._-]?key|authorization|proxy[._-]?authorization|password|passwd|secret|(?:access[._-]?|refresh[._-]?)?token|cookie)"
)
_PROCESS_METRICS: dict[str, list[str] | None] = {
    "process.cpu.time": ["user", "system"],
    "process.cpu.utilization": None,
    "process.memory.usage": None,
    "process.memory.virtual": None,
    "process.thread.count": None,
    "process.open_file_descriptor.count": None,
    "process.context_switches": ["voluntary", "involuntary"],
    "process.disk.io": ["read", "write"],
}


class _HTTPHistogram(metrics.Histogram):
    def __init__(self, histogram: metrics.Histogram) -> None:
        self._histogram = histogram

    def record(
        self,
        amount: float,
        attributes: Attributes = None,
        context: Context | None = None,
    ) -> None:
        self._histogram.record(
            amount, dict(attributes or {}) | dict(_CONTEXT.get()), context
        )


class _HTTPMeter(metrics.NoOpMeter):
    def __init__(self, meter: metrics.Meter, name: str) -> None:
        super().__init__(name)
        self._meter = meter

    def create_histogram(
        self,
        name: str,
        unit: str = "",
        description: str = "",
        *,
        explicit_bucket_boundaries_advisory: Sequence[float] | None = None,
    ) -> metrics.Histogram:
        return _HTTPHistogram(
            self._meter.create_histogram(
                name,
                unit,
                description,
                explicit_bucket_boundaries_advisory=explicit_bucket_boundaries_advisory,
            )
        )


class _HTTPMeterProvider(metrics.NoOpMeterProvider):
    def __init__(self, provider: metrics.MeterProvider) -> None:
        self._provider = provider

    def get_meter(
        self,
        name: str,
        version: str | None = None,
        schema_url: str | None = None,
        attributes: Mapping[str, AnyValue] | None = None,
    ) -> metrics.Meter:
        return _HTTPMeter(
            self._provider.get_meter(name, version, schema_url, attributes), name
        )


class CredentialRedactor:
    """Remove authentication material before telemetry leaves the process."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def register(self, secret: str) -> None:
        """Register an instance's API key for redaction from free text."""
        if secret:
            self._secrets.add(secret)

    def text(self, value: str) -> str:
        """Redact known secrets and credentials embedded in URLs or text."""
        for secret in sorted(self._secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1[REDACTED]@", value)
        return re.sub(
            r"""(?i)((?:api[._-]?key|authorization|password|passwd|secret|(?:access[._-]?|refresh[._-]?)?token)[\"']?\s*[=:]\s*)(?:"[^"]*"|'[^']*'|(?:Bearer|Basic)\s+[^&\s,;]+|[^&\s,;]+)""",
            r"\1[REDACTED]",
            value,
        )

    def value(self, value: AnyValue) -> AnyValue:
        """Redact structured values while retaining useful operation details."""
        if isinstance(value, Mapping):
            return {
                key: "[REDACTED]" if _CREDENTIAL.search(key) else self.value(item)
                for key, item in value.items()
            }
        if isinstance(value, bytes):
            return self.text(value.decode("utf-8", errors="replace"))
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Sequence):
            return [self.value(item) for item in value]
        return value

    def attributes(
        self, attributes: Mapping[str, AnyValue] | None
    ) -> dict[str, AnyValue]:
        """Return sanitized span or event attributes."""
        return {
            key: "[REDACTED]" if _CREDENTIAL.search(key) else self.value(value)
            for key, value in (attributes or {}).items()
        }


class RedactingSpanExporter(SpanExporter):
    """Sanitize automatic HTTP events and exceptions before exporting."""

    def __init__(self, exporter: SpanExporter, redactor: CredentialRedactor) -> None:
        self._exporter = exporter
        self._redactor = redactor

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export sanitized copies without modifying SDK-owned spans."""
        return self._exporter.export(
            [
                ReadableSpan(
                    name=self._redactor.text(span.name),
                    context=span.context,
                    parent=span.parent,
                    resource=span.resource,
                    attributes=self._redactor.attributes(span.attributes),
                    events=[
                        Event(
                            self._redactor.text(event.name),
                            self._redactor.attributes(event.attributes),
                            event.timestamp,
                        )
                        for event in span.events
                    ],
                    links=span.links,
                    kind=span.kind,
                    status=Status(
                        span.status.status_code,
                        self._redactor.text(span.status.description)
                        if span.status.description is not None
                        else None,
                    ),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=span.instrumentation_scope,
                )
                for span in spans
            ]
        )

    def shutdown(self) -> None:
        """Shut down the wrapped exporter."""
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush the wrapped exporter."""
        return self._exporter.force_flush(timeout_millis)


@dataclass(slots=True)
class Operation:
    """Mutable result of an instrumented operation."""

    outcome: str = "succeeded"


class WorkflowTelemetry:
    """Record bounded metrics and detailed spans for one Arr instance."""

    def __init__(
        self,
        meter: metrics.Meter,
        tracer: trace.Tracer,
        service: str = "",
        instance: str = "",
    ) -> None:
        self.attributes = {"arr.service": service, "arr.instance": instance}
        self._meter = meter
        self._tracer = tracer
        self._counters: dict[str, metrics.Counter] = {}
        self._histograms: dict[str, metrics.Histogram] = {}
        self._active = meter.create_gauge("renamarr.job.active", unit="{job}")
        self._last_success = meter.create_gauge(
            "renamarr.scan.last_success_timestamp", unit="s"
        )
        self._last_success.set(0, self.attributes)

    def count(self, name: str, value: int = 1, **attributes: str) -> None:
        """Add a bounded cumulative work measurement."""
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(name, unit="{count}")
        self._counters[name].add(value, self.attributes | attributes)

    def observe(self, name: str, value: float, **attributes: str) -> None:
        """Record a duration or library-size observation."""
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(
                name, unit="{item}" if name == "renamarr.scan.items" else "s"
            )
        self._histograms[name].record(value, self.attributes | attributes)

    @contextmanager
    def span(self, name: str, attributes: Attributes = None) -> Generator[trace.Span]:
        """Create a contextual child span without automatically copying exceptions."""
        token = _CONTEXT.set(self.attributes)
        try:
            with self._tracer.start_as_current_span(
                name,
                attributes=self.attributes | dict(attributes or {}),
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    yield span
                except BaseException as error:
                    span.record_exception(error)
                    span.set_status(StatusCode.ERROR)
                    raise
        finally:
            _CONTEXT.reset(token)

    @contextmanager
    def phase(self, phase: str) -> Generator[None]:
        """Track activity and duration of a scan phase."""
        attributes = self.attributes | {"phase": phase}
        self._active.set(1, attributes)
        try:
            with self.span(f"renamarr.{phase}"):
                yield
        finally:
            self._active.set(0, attributes)

    @contextmanager
    def operation(
        self, category: str, kind: str, attributes: Attributes = None
    ) -> Generator[Operation]:
        """Record one operation, including failures that escape its body."""
        started = perf_counter()
        result = Operation()
        with self.span(f"renamarr.{category}.{kind}", attributes) as span:
            try:
                yield result
            except BaseException:
                if result.outcome == "succeeded":
                    result.outcome = "failed"
                raise
            finally:
                span.set_attribute("outcome", result.outcome)
                if result.outcome != "succeeded":
                    span.set_status(StatusCode.ERROR)
                self.count(
                    f"renamarr.{category}.count", kind=kind, outcome=result.outcome
                )
                self.observe(
                    f"renamarr.{category}.duration",
                    perf_counter() - started,
                    kind=kind,
                    outcome=result.outcome,
                )

    def finish_scan(self, result: ScanResult) -> None:
        """Record library size and the existing media-item summaries."""
        self.observe("renamarr.scan.items", result.items_found)
        for phase, summary in (
            ("analysis", result.analysis),
            ("file_renames", result.file_renames),
            ("folder_renames", result.folder_renames),
        ):
            for outcome, count in (
                ("succeeded", summary.success),
                ("failed", summary.failed),
                ("skipped", summary.skipped),
            ):
                self.count("renamarr.work.items", count, phase=phase, outcome=outcome)
        if result.successful:
            self._last_success.set(time.time(), self.attributes)


class Telemetry:
    """Own process-wide OTel providers, exporters, and instrumentors."""

    def __init__(self) -> None:
        self.redactor = CredentialRedactor()
        self._meter_provider: MeterProvider | metrics.NoOpMeterProvider = (
            metrics.NoOpMeterProvider()
        )
        self._tracer_provider: TracerProvider | trace.NoOpTracerProvider = (
            trace.NoOpTracerProvider()
        )
        self._instrumentors: list[
            URLLib3Instrumentor | ThreadingInstrumentor | SystemMetricsInstrumentor
        ] = []
        self._closed = False
        self._workflows: dict[tuple[str, str], WorkflowTelemetry] = {}
        if os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true":
            return
        try:
            self._configure()
        except Exception:  # noqa: BLE001 - Telemetry cannot prevent application startup.
            self.shutdown()
            self._meter_provider = metrics.NoOpMeterProvider()
            self._tracer_provider = trace.NoOpTracerProvider()
            logger.warning(
                "Unable to initialize OpenTelemetry; continuing without telemetry"
            )

    def _configure(self) -> None:
        resource = Resource.create({"service.name": "renamarr"}).merge(
            OTELResourceDetector().detect()
        )
        if self._enabled("METRICS"):
            self._meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
                shutdown_on_exit=False,
            )
        if self._enabled("TRACES"):
            self._tracer_provider = TracerProvider(
                resource=resource, shutdown_on_exit=False
            )
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    RedactingSpanExporter(OTLPSpanExporter(), self.redactor)
                )
            )
        if isinstance(self._meter_provider, MeterProvider) or isinstance(
            self._tracer_provider, TracerProvider
        ):
            http = URLLib3Instrumentor()
            http.instrument(
                meter_provider=_HTTPMeterProvider(self._meter_provider),
                tracer_provider=self._tracer_provider,
                request_hook=self._request_hook,
                url_filter=self.redactor.text,
                captured_request_headers=[],
                captured_response_headers=[],
            )
            self._instrumentors.append(http)
            threading = ThreadingInstrumentor()
            threading.instrument()
            self._instrumentors.append(threading)
        if isinstance(self._meter_provider, MeterProvider):
            system = SystemMetricsInstrumentor(config=_PROCESS_METRICS)
            system.instrument(meter_provider=self._meter_provider)
            self._instrumentors.append(system)

    @staticmethod
    def _enabled(signal: str) -> bool:
        return (
            bool(
                os.getenv(f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT")
                or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            )
            and os.getenv(f"OTEL_{signal}_EXPORTER", "otlp").lower() != "none"
        )

    def _request_hook(
        self, span: trace.Span, _pool: object, request: RequestInfo
    ) -> None:
        span.set_attributes(_CONTEXT.get())
        body = request.body
        if isinstance(body, (bytes, str)):
            try:
                parsed = json.loads(body)
            except ValueError, UnicodeDecodeError:
                return
            span.set_attribute(
                "http.request.body", json.dumps(self.redactor.value(parsed))
            )

    def workflow(self, service: str, instance: str) -> WorkflowTelemetry:
        """Return persistent instruments and freshness state for an instance."""
        key = service, instance
        if key not in self._workflows:
            self._workflows[key] = WorkflowTelemetry(
                self._meter_provider.get_meter("renamarr"),
                self._tracer_provider.get_tracer("renamarr"),
                service,
                instance,
            )
        return self._workflows[key]

    def shutdown(self) -> None:
        """Flush once, release instrumentors, and isolate exporter failures."""
        if self._closed:
            return
        self._closed = True
        for instrumentor in reversed(self._instrumentors):
            try:
                instrumentor.uninstrument()
            except Exception:  # noqa: BLE001
                logger.warning("Unable to release OpenTelemetry instrumentation")
        for provider in (self._meter_provider, self._tracer_provider):
            if isinstance(provider, (MeterProvider, TracerProvider)):
                try:
                    provider.force_flush(timeout_millis=5000)
                except Exception:  # noqa: BLE001
                    logger.warning("Unable to flush OpenTelemetry")
                finally:
                    try:
                        provider.shutdown()
                    except Exception:  # noqa: BLE001
                        logger.warning("Unable to shut down OpenTelemetry")


def disabled_workflow() -> WorkflowTelemetry:
    """Return isolated no-op instruments for direct library use."""
    return WorkflowTelemetry(
        metrics.NoOpMeterProvider().get_meter("renamarr"),
        trace.NoOpTracerProvider().get_tracer("renamarr"),
    )
