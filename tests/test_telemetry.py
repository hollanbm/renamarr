import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import grpc
import pytest
from opentelemetry._logs import NoOpLoggerProvider
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (
    LogsServiceServicer,
    add_LogsServiceServicer_to_server,
)
from pytest_mock import MockerFixture
from structlog.contextvars import bound_contextvars

from renamarr.telemetry import configure_telemetry

_EMIT_LOGS = """
import logging
import structlog
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span
from structlog.contextvars import bound_contextvars
from renamarr.telemetry import configure_telemetry

configure_telemetry()
logging.getLogger().setLevel(logging.INFO)
structlog.configure(
    processors=[structlog.contextvars.merge_contextvars,
                structlog.stdlib.render_to_log_kwargs],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
span = NonRecordingSpan(SpanContext(123, 456, False, TraceFlags(1)))
with bound_contextvars(arr_type="sonarr", instance="shows", item="Example"):
    with use_span(span):
        try:
            raise ValueError("rename failed")
        except ValueError:
            structlog.get_logger("renamarr.test").exception(
                "Batch failed", renamed_count=12, dry_run=True,
            )
        logging.getLogger("sonarr.rest").warning(
            "Dependency event", extra={"arr_type": "radarr"},
        )
"""


def _run_telemetry(
    environment: dict[str, str], script: str = _EMIT_LOGS
) -> subprocess.CompletedProcess[str]:
    clean_environment = {
        key: value for key, value in os.environ.items() if not key.startswith("OTEL_")
    }
    clean_environment.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
        OTEL_BLRP_SCHEDULE_DELAY="60000",
    )
    clean_environment.update(environment)
    return subprocess.run(
        [sys.executable, "-c", script],
        env=clean_environment,
        capture_output=True,
        # Allow posix_spawn to avoid forking while the gRPC receiver has threads.
        close_fds=False,
        text=True,
        timeout=15,
        check=False,
    )


def test_configuration_delegates_to_sdk_and_preserves_local_handlers(
    mocker: MockerFixture,
) -> None:
    configurator = mocker.patch(
        "renamarr.telemetry.OpenTelemetryConfigurator", autospec=True
    )
    instrumentor = mocker.patch("renamarr.telemetry.LoggingInstrumentor", autospec=True)
    operations = mocker.Mock()
    operations.attach_mock(configurator.return_value.configure, "configure")
    operations.attach_mock(instrumentor.return_value.instrument, "instrument")
    local_handler = logging.NullHandler()
    with closing(LoggingHandler(logger_provider=NoOpLoggerProvider())) as handler:
        mocker.patch.object(logging.getLogger(), "handlers", [local_handler, handler])

        assert configure_telemetry() is None

        assert operations.mock_calls == [
            mocker.call.configure(),
            mocker.call.instrument(set_logging_format=False),
        ]
        assert len(handler.filters) == 1
        assert local_handler.filters == []


def test_sdk_configuration_failure_propagates_before_instrumentation(
    mocker: MockerFixture,
) -> None:
    configurator = mocker.patch("renamarr.telemetry.OpenTelemetryConfigurator")
    instrumentor = mocker.patch("renamarr.telemetry.LoggingInstrumentor")
    configurator.return_value.configure.side_effect = RuntimeError("invalid setting")

    with pytest.raises(RuntimeError, match="invalid setting"):
        configure_telemetry()

    instrumentor.assert_not_called()


@pytest.mark.parametrize(
    ("name", "exported"),
    [
        ("renamarr", True),
        ("sonarr.rest", True),
        ("urllib3_adapter", True),
        ("opentelemetry", False),
        ("opentelemetry.sdk._shared_internal", False),
        ("urllib3.connectionpool", False),
        ("requests", False),
        ("httpcore.connection", False),
        ("httpx", False),
    ],
)
def test_export_filter_keeps_context_and_excludes_exporter_diagnostics(
    name: str, exported: bool, mocker: MockerFixture
) -> None:
    mocker.patch("renamarr.telemetry.OpenTelemetryConfigurator")
    mocker.patch("renamarr.telemetry.LoggingInstrumentor")
    handler = LoggingHandler(logger_provider=NoOpLoggerProvider())
    mocker.patch.object(logging.getLogger(), "handlers", [handler])
    configure_telemetry()
    record = logging.LogRecord(name, logging.ERROR, __file__, 1, "An event", (), None)
    record.__dict__["arr_type"] = "radarr"

    with bound_contextvars(arr_type="sonarr", instance="shows"):
        assert bool(handler.filter(record)) is exported

    assert record.__dict__["arr_type"] == "radarr"
    assert record.__dict__["instance"] == "shows"
    handler.close()


@pytest.fixture
def otlp_receiver() -> Iterator[
    tuple[str, list[tuple[str, str | None, ExportLogsServiceRequest]]]
]:
    received: list[tuple[str, str | None, ExportLogsServiceRequest]] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            request = ExportLogsServiceRequest()
            request.ParseFromString(payload)
            received.append((self.path, self.headers.get("x-test-token"), request))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Receiver) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", received
        finally:
            server.shutdown()
            worker.join(timeout=2)


@pytest.mark.parametrize(
    ("environment", "service_name", "logs_endpoint"),
    [
        ({}, "unknown_service", False),
        ({"OTEL_RESOURCE_ATTRIBUTES": "service.name=resource"}, "resource", True),
        (
            {
                "OTEL_SERVICE_NAME": "application",
                "OTEL_RESOURCE_ATTRIBUTES": "service.name=resource",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
                "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/protobuf",
            },
            "application",
            True,
        ),
    ],
    ids=["sdk-defaults", "resource-service", "signal-and-service-overrides"],
)
def test_sdk_http_export_preserves_attributes_and_flushes_on_process_exit(
    environment: dict[str, str],
    service_name: str,
    logs_endpoint: bool,
    otlp_receiver: tuple[str, list[tuple[str, str | None, ExportLogsServiceRequest]]],
) -> None:
    endpoint, received = otlp_receiver
    settings = {
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": "x-test-token=base",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-test-token=logs",
    }
    settings.update(environment)
    settings["OTEL_RESOURCE_ATTRIBUTES"] = (
        settings.get("OTEL_RESOURCE_ATTRIBUTES", "")
        + ",deployment.environment.name=test"
    ).lstrip(",")
    if logs_endpoint:
        settings["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:1/unused"
        settings["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] = f"{endpoint}/custom/logs"

    result = _run_telemetry(settings)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert len(received) == 1
    path, token, request = received[0]
    assert path == ("/custom/logs" if logs_endpoint else "/v1/logs")
    assert token == "logs"
    resource_logs = request.resource_logs[0]
    resource = {
        attribute.key: attribute.value.string_value
        for attribute in resource_logs.resource.attributes
    }
    assert resource["service.name"].startswith(service_name)
    assert resource["deployment.environment.name"] == "test"
    records = [
        record for scope in resource_logs.scope_logs for record in scope.log_records
    ]
    assert len(records) == 2
    record, dependency_record = records
    assert record.body.string_value == "Batch failed"
    attributes = {attribute.key: attribute.value for attribute in record.attributes}
    assert attributes["arr_type"].string_value == "sonarr"
    assert attributes["instance"].string_value == "shows"
    assert attributes["item"].string_value == "Example"
    assert attributes["renamed_count"].int_value == 12
    assert attributes["dry_run"].bool_value is True
    assert attributes["exception.type"].string_value == "ValueError"
    assert attributes["exception.message"].string_value == "rename failed"
    assert (
        "ValueError: rename failed" in attributes["exception.stacktrace"].string_value
    )
    assert int.from_bytes(record.trace_id) == 123
    assert int.from_bytes(record.span_id) == 456
    dependency_attributes = {
        attribute.key: attribute.value for attribute in dependency_record.attributes
    }
    assert dependency_attributes["arr_type"].string_value == "radarr"
    assert dependency_attributes["instance"].string_value == "shows"


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"OTEL_LOGS_EXPORTER": "none"},
        {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_SDK_DISABLED": "true"},
        {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "false"},
    ],
    ids=["default", "none", "sdk-disabled", "logging-instrumentation-disabled"],
)
def test_sdk_settings_disable_log_export(
    environment: dict[str, str],
    otlp_receiver: tuple[str, list[tuple[str, str | None, ExportLogsServiceRequest]]],
) -> None:
    endpoint, received = otlp_receiver
    result = _run_telemetry(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            **environment,
        }
    )

    assert result.returncode == 0, result.stderr
    assert received == []


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"OTEL_LOGS_EXPORTER": "invalid"}, "Requested component 'invalid' not found"),
        (
            {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_PROTOCOL": "invalid"},
            "Unsupported OTLP protocol 'invalid' is configured",
        ),
    ],
    ids=["unknown-exporter", "unknown-protocol"],
)
def test_sdk_rejects_invalid_export_configuration(
    environment: dict[str, str], message: str
) -> None:
    result = _run_telemetry(environment)

    assert result.returncode != 0
    assert message in result.stderr


def test_sdk_supports_console_exporter() -> None:
    result = _run_telemetry(
        {"OTEL_LOGS_EXPORTER": "console"},
        """
import logging
from renamarr.telemetry import configure_telemetry
configure_telemetry()
logging.getLogger("renamarr").warning("Console event", extra={"count": 12})
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    record = json.loads(result.stdout)
    assert record["body"] == "Console event"
    assert record["attributes"]["count"] == 12


@pytest.mark.parametrize("legacy_handler", [False, True], ids=["current", "legacy"])
def test_export_failures_remain_local_without_feedback_into_exporter(
    legacy_handler: bool,
) -> None:
    result = _run_telemetry(
        {
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED": str(
                legacy_handler
            ).lower(),
        },
        """
import logging
import os
import sys
import warnings
from opentelemetry._logs import get_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from renamarr.telemetry import configure_telemetry

export_count = 0
exported_messages = []
def fail_export(self, batch):
    global export_count
    export_count += 1
    exported_messages.extend(record.log_record.body for record in batch)
    raise RuntimeError("collector unavailable")

OTLPLogExporter.export = fail_export
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
legacy_handler = os.environ["OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED"] == "true"
with warnings.catch_warnings(record=True) as recorded:
    warnings.simplefilter("error")
    warnings.filterwarnings(
        "always", category=DeprecationWarning,
        message=r"The `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED` environment variable .*",
    )
    warnings.filterwarnings(
        "always", category=DeprecationWarning,
        message=r"`LoggingHandler` in `opentelemetry-sdk` is deprecated\\. .*",
    )
    configure_telemetry()
assert len(recorded) == (2 if legacy_handler else 0), recorded
logging.getLogger("renamarr").warning("Job completed")
get_logger_provider().force_flush()
logging.getLogger("renamarr").warning("Local logging still works")
get_logger_provider().force_flush()
assert export_count == 2, export_count
if legacy_handler:
    assert exported_messages.pop(0).startswith("Skipping installation of LoggingHandler")
assert exported_messages == ["Job completed", "Local logging still works"], exported_messages
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Job completed" in result.stdout
    assert "Local logging still works" in result.stdout
    assert "RuntimeError: collector unavailable" in result.stdout


def test_sdk_defaults_to_grpc_and_flushes_on_process_exit() -> None:
    received: list[ExportLogsServiceRequest] = []

    class Receiver(LogsServiceServicer):
        def Export(
            self, request: ExportLogsServiceRequest, context: grpc.ServicerContext
        ) -> ExportLogsServiceResponse:
            received.append(request)
            return ExportLogsServiceResponse()

    with ThreadPoolExecutor(max_workers=1) as executor:
        server = grpc.server(executor)
        add_LogsServiceServicer_to_server(Receiver(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            result = _run_telemetry(
                {
                    "OTEL_LOGS_EXPORTER": "otlp",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{port}",
                }
            )
        finally:
            server.stop(grace=0).wait(timeout=2)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert len(received) == 1
    records = [
        record
        for resource in received[0].resource_logs
        for scope in resource.scope_logs
        for record in scope.log_records
    ]
    assert len(records) == 2
    assert records[0].body.string_value == "Batch failed"
