"""Optional OpenTelemetry log export and its owned resources."""

import logging
import os
from contextlib import ExitStack
from dataclasses import dataclass, field

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import OTELResourceDetector, Resource


class _ExcludeExporterDiagnostics(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.split(".", 1)[0] not in {
            "opentelemetry",
            "requests",
            "urllib3",
            "httpcore",
            "httpx",
        }


@dataclass
class Telemetry:
    """An unattached OTLP handler and its independently owned SDK provider."""

    handler: logging.Handler
    _provider: LoggerProvider
    _closed: bool = field(default=False, init=False)

    def shutdown(self) -> None:
        """Drain pending logs and close resources at most once."""
        if self._closed:
            return
        self._closed = True
        try:
            self._provider.shutdown()
        finally:
            self.handler.close()


def configure_telemetry(level: int) -> Telemetry | None:
    """Create optional OTLP/HTTP log export from standard OTEL settings.

    The caller attaches the handler and owns shutdown. No global providers are
    installed, so future metrics and tracing configuration stays independent.

    Raises:
        ValueError: An enabled exporter or protocol is unsupported.
    """
    if os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true":
        return None
    exporter_name = os.getenv("OTEL_LOGS_EXPORTER", "none").strip().lower()
    if exporter_name == "none":
        return None
    if exporter_name != "otlp":
        raise ValueError("OTEL_LOGS_EXPORTER must be 'none' or 'otlp'")
    protocol = os.getenv(
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
        os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
    )
    if protocol != "http/protobuf":
        raise ValueError("OTLP log export supports only the 'http/protobuf' protocol")

    resource = Resource.create({"service.name": "renamarr"}).merge(
        OTELResourceDetector().detect()
    )
    with ExitStack() as resources:
        provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        resources.callback(provider.shutdown)
        with ExitStack() as exporter_resources:
            exporter = OTLPLogExporter()
            exporter_resources.callback(exporter.shutdown)
            processor = BatchLogRecordProcessor(exporter)
            exporter_resources.pop_all()
        with ExitStack() as processor_resources:
            processor_resources.callback(processor.shutdown)
            provider.add_log_record_processor(processor)
            processor_resources.pop_all()
        handler = LoggingHandler(level=level, logger_provider=provider)
        resources.callback(handler.close)
        handler.addFilter(_ExcludeExporterDiagnostics())
        telemetry = Telemetry(handler, provider)
        resources.pop_all()
        return telemetry
