"""OpenTelemetry-managed configuration with Renamarr's logging integration."""

import logging

from opentelemetry.distro import OpenTelemetryConfigurator
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggingHandler as SDKLoggingHandler
from structlog.contextvars import get_contextvars


class _ExportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_contextvars().items():
            record.__dict__.setdefault(key, value)
        return record.name.split(".", 1)[0] not in {
            "opentelemetry",
            "requests",
            "urllib3",
            "httpcore",
            "httpx",
        }


def configure_telemetry() -> None:
    """Configure process-wide telemetry using OpenTelemetry's environment settings.

    OpenTelemetry owns providers, exporters, and shutdown. Renamarr preserves its
    local formatting and keeps exporter diagnostics out of the export pipeline.
    """
    OpenTelemetryConfigurator().configure()
    LoggingInstrumentor().instrument(set_logging_format=False)
    for handler in logging.getLogger().handlers:
        if isinstance(handler, LoggingHandler | SDKLoggingHandler):
            handler.addFilter(_ExportFilter())
