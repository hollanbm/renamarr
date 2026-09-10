import logging
import os
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import MagicMock

import pytest
from opentelemetry._logs import get_logger_provider
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    use_span,
)
from pytest_mock import MockerFixture

from renamarr.telemetry import Telemetry, configure_telemetry


@pytest.fixture(autouse=True)
def telemetry_environment(mocker: MockerFixture) -> None:
    mocker.patch.dict(os.environ, {}, clear=True)


@pytest.fixture
def sdk(mocker: MockerFixture) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    mocker.patch.dict(os.environ, {"OTEL_LOGS_EXPORTER": "otlp"})
    provider = mocker.patch("renamarr.telemetry.LoggerProvider", autospec=True)
    exporter = mocker.patch("renamarr.telemetry.OTLPLogExporter", autospec=True)
    processor = mocker.patch(
        "renamarr.telemetry.BatchLogRecordProcessor", autospec=True
    )
    handler = mocker.patch("renamarr.telemetry.LoggingHandler", autospec=True)
    return provider, exporter, processor, handler


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"OTEL_LOGS_EXPORTER": "none"},
        {"OTEL_LOGS_EXPORTER": " NONE "},
        {"OTEL_SDK_DISABLED": "TRUE", "OTEL_LOGS_EXPORTER": "invalid"},
    ],
    ids=["default", "none", "normalized", "sdk-disabled"],
)
def test_disabled_export_does_not_initialize_sdk(
    environment: dict[str, str], mocker: MockerFixture
) -> None:
    mocker.patch.dict(os.environ, environment)
    provider = mocker.patch("renamarr.telemetry.LoggerProvider")

    assert configure_telemetry(logging.INFO) is None

    provider.assert_not_called()


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"OTEL_LOGS_EXPORTER": "console"}, "OTEL_LOGS_EXPORTER"),
        ({"OTEL_LOGS_EXPORTER": ""}, "OTEL_LOGS_EXPORTER"),
        (
            {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"},
            "http/protobuf",
        ),
        (
            {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "grpc"},
            "http/protobuf",
        ),
    ],
    ids=["unknown-exporter", "empty-exporter", "global-protocol", "logs-protocol"],
)
def test_unsupported_export_configuration_is_rejected(
    environment: dict[str, str], message: str, mocker: MockerFixture
) -> None:
    mocker.patch.dict(os.environ, environment)

    with pytest.raises(ValueError, match=message):
        configure_telemetry(logging.INFO)


@pytest.mark.parametrize(
    ("environment", "service_name"),
    [
        ({}, "renamarr"),
        (
            {"OTEL_RESOURCE_ATTRIBUTES": "service.name=resource,host.name=example"},
            "resource",
        ),
        (
            {
                "OTEL_SERVICE_NAME": "application",
                "OTEL_RESOURCE_ATTRIBUTES": "service.name=resource,host.name=example",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
                "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/protobuf",
            },
            "application",
        ),
    ],
    ids=["default", "resource", "service-and-protocol-override"],
)
def test_configuration_preserves_resource_precedence_and_owns_its_provider(
    environment: dict[str, str],
    service_name: str,
    sdk: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    mocker: MockerFixture,
) -> None:
    mocker.patch.dict(os.environ, environment)
    provider, exporter, processor, handler = sdk
    global_provider = get_logger_provider()
    root_handlers = logging.getLogger().handlers.copy()

    telemetry = configure_telemetry(logging.DEBUG)

    assert telemetry is not None
    resource = provider.call_args.kwargs["resource"]
    assert resource.attributes["service.name"] == service_name
    assert provider.call_args.kwargs["shutdown_on_exit"] is False
    exporter.assert_called_once_with()
    processor.assert_called_once_with(exporter.return_value)
    provider.return_value.add_log_record_processor.assert_called_once_with(
        processor.return_value
    )
    handler.assert_called_once_with(
        level=logging.DEBUG, logger_provider=provider.return_value
    )
    assert telemetry.handler is handler.return_value
    assert get_logger_provider() is global_provider
    assert logging.getLogger().handlers == root_handlers
    telemetry.shutdown()


@pytest.mark.parametrize(
    "phase", ["exporter", "processor", "register", "handler", "filter"]
)
def test_partial_configuration_closes_all_initialized_resources(
    phase: str, sdk: tuple[MagicMock, MagicMock, MagicMock, MagicMock]
) -> None:
    provider, exporter, processor, handler = sdk
    failing_operation = {
        "exporter": exporter,
        "processor": processor,
        "register": provider.return_value.add_log_record_processor,
        "handler": handler,
        "filter": handler.return_value.addFilter,
    }[phase]
    failing_operation.side_effect = RuntimeError("setup failed")

    with pytest.raises(RuntimeError, match="setup failed"):
        configure_telemetry(logging.INFO)

    provider.return_value.shutdown.assert_called_once_with()
    assert exporter.return_value.shutdown.call_count == (phase == "processor")
    assert processor.return_value.shutdown.call_count == (phase == "register")
    assert handler.return_value.close.call_count == (phase == "filter")


@pytest.mark.parametrize("failure", [None, "provider", "handler"])
def test_shutdown_drains_before_closing_and_stays_idempotent_after_failure(
    failure: str | None, mocker: MockerFixture
) -> None:
    provider = mocker.Mock()
    handler = mocker.Mock(spec=logging.Handler)
    calls = mocker.Mock()
    calls.attach_mock(provider, "provider")
    calls.attach_mock(handler, "handler")
    telemetry = Telemetry(handler, provider)
    if failure is not None:
        operation = provider.shutdown if failure == "provider" else handler.close
        operation.side_effect = RuntimeError("shutdown failed")
        with pytest.raises(RuntimeError, match="shutdown failed"):
            telemetry.shutdown()
    else:
        telemetry.shutdown()
    telemetry.shutdown()

    assert calls.mock_calls == [
        mocker.call.provider.shutdown(),
        mocker.call.handler.close(),
    ]


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
def test_exporter_diagnostics_are_filtered_without_hiding_application_logs(
    name: str, exported: bool, mocker: MockerFixture
) -> None:
    mocker.patch.dict(os.environ, {"OTEL_LOGS_EXPORTER": "otlp"})
    exporter = InMemoryLogRecordExporter()
    mocker.patch("renamarr.telemetry.OTLPLogExporter", return_value=exporter)
    telemetry = configure_telemetry(logging.INFO)
    assert telemetry is not None
    record = logging.LogRecord(name, logging.ERROR, __file__, 1, "An event", (), None)

    telemetry.handler.handle(record)
    telemetry.shutdown()

    assert len(exporter.get_finished_logs()) == int(exported)


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


@pytest.mark.parametrize("logs_endpoint", [False, True], ids=["base-url", "logs-url"])
def test_http_export_preserves_attributes_exceptions_trace_and_endpoint_precedence(
    logs_endpoint: bool,
    otlp_receiver: tuple[str, list[tuple[str, str | None, ExportLogsServiceRequest]]],
    mocker: MockerFixture,
) -> None:
    endpoint, received = otlp_receiver
    environment = {
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": "x-test-token=base",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-test-token=logs",
        "OTEL_RESOURCE_ATTRIBUTES": "deployment.environment.name=test",
        "OTEL_BLRP_SCHEDULE_DELAY": "60000",
    }
    if logs_endpoint:
        environment["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:1/unused"
        environment["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] = f"{endpoint}/custom/logs"
    mocker.patch.dict(os.environ, environment)
    telemetry = configure_telemetry(logging.INFO)
    assert telemetry is not None
    logger = logging.getLogger("renamarr.telemetry_test")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    mocker.patch.object(logger, "handlers", [telemetry.handler])
    mocker.patch.object(logger, "propagate", False)
    span = NonRecordingSpan(SpanContext(123, 456, False, TraceFlags(1)))

    try:
        with use_span(span):
            try:
                raise ValueError("rename failed")
            except ValueError:
                logger.exception(
                    "Batch failed",
                    extra={
                        "arr_type": "sonarr",
                        "instance": "shows",
                        "item": "Example",
                        "renamed_count": 12,
                    },
                )
    finally:
        telemetry.shutdown()
        logger.setLevel(previous_level)

    assert len(received) == 1
    path, token, request = received[0]
    assert path == ("/custom/logs" if logs_endpoint else "/v1/logs")
    assert token == "logs"
    resource_logs = request.resource_logs[0]
    resource = {
        attribute.key: attribute.value.string_value
        for attribute in resource_logs.resource.attributes
    }
    assert resource["service.name"] == "renamarr"
    assert resource["deployment.environment.name"] == "test"
    record = resource_logs.scope_logs[0].log_records[0]
    assert record.body.string_value == "Batch failed"
    attributes = {attribute.key: attribute.value for attribute in record.attributes}
    assert attributes["arr_type"].string_value == "sonarr"
    assert attributes["instance"].string_value == "shows"
    assert attributes["item"].string_value == "Example"
    assert attributes["renamed_count"].int_value == 12
    assert attributes["exception.type"].string_value == "ValueError"
    assert attributes["exception.message"].string_value == "rename failed"
    assert (
        "ValueError: rename failed" in attributes["exception.stacktrace"].string_value
    )
    assert int.from_bytes(record.trace_id) == 123
    assert int.from_bytes(record.span_id) == 456


def test_export_failure_leaves_local_logging_operational(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    mocker.patch.dict(os.environ, {"OTEL_LOGS_EXPORTER": "otlp"})
    exporter = mocker.patch(
        "renamarr.telemetry.OTLPLogExporter", autospec=True
    ).return_value
    exporter.export.side_effect = RuntimeError("collector unavailable")
    telemetry = configure_telemetry(logging.WARNING)
    assert telemetry is not None
    root = logging.getLogger()
    root.addHandler(telemetry.handler)
    try:
        logging.getLogger("renamarr.telemetry_test").warning("Job completed")
        telemetry.shutdown()
        logging.getLogger("renamarr.telemetry_test").warning(
            "Local logging still works"
        )
    finally:
        root.removeHandler(telemetry.handler)
        telemetry.shutdown()

    assert "Job completed" in caplog.text
    assert "collector unavailable" in caplog.text
    assert "Local logging still works" in caplog.text
    exporter.export.assert_called_once()
    exporter.shutdown.assert_called_once()
