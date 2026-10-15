import io
import json
import os
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.instrumentation.urllib3 import RequestInfo
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode
from pytest_mock import MockerFixture

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandPollingSettings, CommandStatus
from renamarr.models.media import FileRenameBatch, FileRenameCandidate, MediaItem
from renamarr.models.scan import ScanResult, WorkSummary
from renamarr.protocols import ArrAdapter
from renamarr.renamarr import Renamarr
from renamarr.telemetry import (
    CredentialRedactor,
    RedactingSpanExporter,
    Telemetry,
    WorkflowTelemetry,
)


@pytest.fixture(autouse=True)
def isolated_otel_environment(mocker: MockerFixture) -> None:
    mocker.patch.dict(
        os.environ,
        {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("OTEL_")
        },
        clear=True,
    )


@pytest.fixture
def instruments() -> Iterator[
    tuple[WorkflowTelemetry, InMemoryMetricReader, InMemorySpanExporter]
]:
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    workflow = WorkflowTelemetry(
        meter_provider.get_meter("test"),
        tracer_provider.get_tracer("test"),
        "sonarr",
        "test",
    )
    yield workflow, reader, exporter
    meter_provider.shutdown()
    tracer_provider.shutdown()


def measurements(reader: InMemoryMetricReader) -> dict[str, list]:
    data = reader.get_metrics_data()
    assert data is not None
    return {
        metric.name: list(metric.data.data_points)
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


def test_redaction_preserves_media_and_removes_credentials() -> None:
    redactor = CredentialRedactor()
    redactor.register("")
    redactor.register("known-key")
    body = {
        "title": "A title",
        "path": "/media/A title",
        "headers": {"Authorization": "Bearer private"},
        "nested": [{"api_key": "hidden"}, 3, True, None],
        "bytes": b"known-key",
    }
    cleaned = redactor.value(body)
    assert cleaned == {
        "title": "A title",
        "path": "/media/A title",
        "headers": {"Authorization": "[REDACTED]"},
        "nested": [{"api_key": "[REDACTED]"}, 3, True, None],
        "bytes": "[REDACTED]",
    }
    assert (
        redactor.text(
            "https://user:password@example.test/file?api_key=unknown&x=1 known-key"
        )
        == "https://[REDACTED]@example.test/file?api_key=[REDACTED]&x=1 [REDACTED]"
    )
    assert redactor.attributes(
        {"http.request.header.x-api-key": "private", "media.title": "A title"}
    ) == {"http.request.header.x-api-key": "[REDACTED]", "media.title": "A title"}
    assert redactor.attributes(None) == {}
    assert "unknown-secret" not in redactor.text(
        '{"password": "unknown-secret with spaces"}'
    )
    assert "auth-secret" not in redactor.text("Authorization=Bearer auth-secret")


def test_exporter_sanitizes_status_events_and_attributes(mocker: MockerFixture) -> None:
    redactor = CredentialRedactor()
    redactor.register("top-secret")
    sink = InMemorySpanExporter()
    exporter = RedactingSpanExporter(sink, redactor)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("top-secret") as span:
        span.set_attribute("media.path", "/media/top-secret")
        span.set_status(Status(StatusCode.ERROR, "top-secret"))
        span.record_exception(ValueError("top-secret"))
    span = sink.get_finished_spans()[0]
    assert span.name == "[REDACTED]"
    assert span.attributes is not None
    assert span.attributes["media.path"] == "/media/[REDACTED]"
    assert span.status.description == "[REDACTED]"
    assert "top-secret" not in str(span.events[0].attributes)
    exporter.export([ReadableSpan("plain")])
    flush = mocker.patch.object(sink, "force_flush", return_value=True)
    assert exporter.force_flush(123)
    flush.assert_called_once_with(123)
    provider.shutdown()


@pytest.mark.parametrize(
    "environment, signals",
    [
        ({}, set()),
        (
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"},
            {"metrics", "traces"},
        ),
        (
            {"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://localhost:4318/v1/metrics"},
            {"metrics"},
        ),
        (
            {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"},
            {"traces"},
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                "OTEL_METRICS_EXPORTER": "none",
            },
            {"traces"},
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                "OTEL_TRACES_EXPORTER": "none",
            },
            {"metrics"},
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                "OTEL_SDK_DISABLED": "TRUE",
            },
            set(),
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                "OTEL_METRICS_EXPORTER": "none",
                "OTEL_TRACES_EXPORTER": "none",
            },
            set(),
        ),
    ],
)
def test_activation_and_instrumentor_cleanup(
    mocker: MockerFixture, environment: dict[str, str], signals: set[str]
) -> None:
    mocker.patch.dict(os.environ, environment)
    metric_exporter = mocker.patch("renamarr.telemetry.OTLPMetricExporter")
    reader = InMemoryMetricReader()
    mocker.patch(
        "renamarr.telemetry.PeriodicExportingMetricReader", return_value=reader
    )
    span_exporter = InMemorySpanExporter()
    mocker.patch("renamarr.telemetry.OTLPSpanExporter", return_value=span_exporter)
    telemetry = Telemetry()
    try:
        first = telemetry.workflow("sonarr", "first")
        assert first is telemetry.workflow("sonarr", "first")
        second = telemetry.workflow("radarr", "second")
        assert first is not second
        with first.operation("scan", "run"):
            first.count("renamarr.rename.confirmed", 2, kind="file")
        with second.operation("scan", "run"):
            pass
        assert metric_exporter.called == ("metrics" in signals)
    finally:
        telemetry.shutdown()
        telemetry.shutdown()
    spans = span_exporter.get_finished_spans()
    assert bool(spans) == ("traces" in signals)
    if spans:
        assert spans[0].resource.attributes["service.name"] == "renamarr"
        assert spans[0].attributes is not None
        assert spans[1].attributes is not None
        assert spans[0].attributes["arr.instance"] == "first"
        assert spans[1].attributes["arr.instance"] == "second"
    if "metrics" in signals:
        points = measurements(reader)
        assert "process.memory.usage" in points
        assert {
            p.attributes["arr.instance"] for p in points["renamarr.scan.count"]
        } == {"first", "second"}


@pytest.mark.parametrize(
    "body",
    [
        b'{"files": [1], "password": "private"}',
        '{"title": "A", "path": "/media/A"}',
        b"\xff",
        "invalid",
        io.BytesIO(b"not consumed"),
        None,
    ],
)
def test_request_capture_is_structured_and_does_not_consume_streams(
    instruments, body
) -> None:
    workflow, _, exporter = instruments
    telemetry = Telemetry()
    with workflow.span("http") as span:
        telemetry._request_hook(span, None, RequestInfo("POST", "/command", None, body))
    captured = exporter.get_finished_spans()[0].attributes
    assert captured["arr.instance"] == "test"
    if isinstance(body, (str, bytes)) and body[:1] in ("{", b"{"):
        assert "private" not in captured["http.request.body"]
        assert json.loads(captured["http.request.body"])
    else:
        assert "http.request.body" not in captured
    if isinstance(body, io.BytesIO):
        assert body.tell() == 0
    telemetry.shutdown()


def test_operation_metrics_nested_spans_and_freshness(
    instruments, mocker: MockerFixture
) -> None:
    workflow, reader, exporter = instruments
    mocker.patch(
        "renamarr.telemetry.perf_counter", side_effect=[10.0, 13.5, 20.0, 22.0]
    )
    mocker.patch("renamarr.telemetry.time.time", return_value=1234.0)
    with (
        workflow.operation("scan", "run"),
        workflow.phase("file_renames"),
        workflow.operation("operation", "file"),
    ):
        workflow.count("renamarr.rename.confirmed", 2, kind="file")
    workflow.finish_scan(
        ScanResult(
            2,
            WorkSummary(skipped=2),
            WorkSummary(success=2),
            WorkSummary(skipped=2),
            (),
        )
    )
    points = measurements(reader)
    assert points["renamarr.scan.duration"][0].sum == 12.0
    assert points["renamarr.operation.duration"][0].sum == 6.5
    assert points["renamarr.scan.last_success_timestamp"][0].value == 1234.0
    assert points["renamarr.job.active"][0].value == 0
    assert points["renamarr.scan.items"][0].sum == 2
    spans = exporter.get_finished_spans()
    assert spans[0].parent.span_id == spans[1].context.span_id
    assert spans[1].parent.span_id == spans[2].context.span_id
    for values in points.values():
        for point in values:
            assert set(point.attributes) <= {
                "arr.service",
                "arr.instance",
                "kind",
                "phase",
                "outcome",
            }


@pytest.mark.parametrize("outcome", ["succeeded", "status_check_error", "timed_out"])
def test_escaping_failure_records_once_and_clears_activity(
    instruments, outcome: str
) -> None:
    workflow, reader, exporter = instruments
    with (
        pytest.raises(ValueError, match="failure"),
        workflow.operation("scan", "run") as operation,
    ):
        operation.outcome = outcome
        with workflow.phase("discovery"):
            raise ValueError("failure")
    points = measurements(reader)
    assert points["renamarr.scan.count"][0].value == 1
    assert points["renamarr.scan.count"][0].attributes["outcome"] == (
        "failed" if outcome == "succeeded" else outcome
    )
    assert points["renamarr.job.active"][0].value == 0
    assert points["renamarr.scan.last_success_timestamp"][0].value == 0
    assert all(
        span.status.status_code == StatusCode.ERROR
        for span in exporter.get_finished_spans()
    )


def test_shutdown_continues_after_flush_and_shutdown_errors(
    mocker: MockerFixture,
) -> None:
    mocker.patch.dict(
        os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"}
    )
    reader = InMemoryMetricReader()
    mocker.patch(
        "renamarr.telemetry.PeriodicExportingMetricReader", return_value=reader
    )
    mocker.patch(
        "renamarr.telemetry.OTLPSpanExporter", return_value=InMemorySpanExporter()
    )
    telemetry = Telemetry()
    assert isinstance(telemetry._meter_provider, MeterProvider)
    original_shutdown = telemetry._meter_provider.shutdown
    mocker.patch.object(
        telemetry._meter_provider, "force_flush", side_effect=RuntimeError("offline")
    )
    mocker.patch.object(
        telemetry._meter_provider, "shutdown", side_effect=RuntimeError("offline")
    )
    telemetry.shutdown()
    original_shutdown()


def test_actual_workflow_counts_files_separately_from_items(
    instruments, mocker: MockerFixture
) -> None:
    workflow, reader, exporter = instruments
    adapter = mocker.Mock(spec=ArrAdapter)
    item = MediaItem(1, "A title", "/root/old")
    adapter.list_media_items.return_value = [item]
    adapter.get_file_rename_candidate.side_effect = [
        FileRenameCandidate(item, (10, 10, 11), "A title"),
        None,
    ]
    adapter.build_file_rename_batches.return_value = [
        FileRenameBatch((1,), (10, 10, 11), "A title")
    ]
    adapter.start_file_rename.return_value = 20
    adapter.get_command_status.return_value = CommandStatus(True, True)
    with workflow.operation("scan", "run") as operation:
        result = Renamarr("test", adapter, telemetry=workflow).scan()
        operation.outcome = "succeeded" if result.successful else "failed"
    points = measurements(reader)
    assert points["renamarr.rename.candidates"][0].value == 2
    assert points["renamarr.rename.requested"][0].value == 2
    assert points["renamarr.rename.confirmed"][0].value == 2
    assert (
        next(
            p
            for p in points["renamarr.work.items"]
            if p.attributes["phase"] == "file_renames"
            and p.attributes["outcome"] == "succeeded"
        ).value
        == 1
    )
    verification = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == "renamarr.verification"
    )
    assert verification.attributes["media.title"] == "A title"
    assert verification.attributes["media.path"] == "/root/old"


@pytest.mark.parametrize(
    "environment",
    [
        {"OTEL_SERVICE_NAME": "custom"},
        {
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=custom,deployment.environment.name=test"
        },
    ],
)
def test_resource_environment_overrides_defaults(
    mocker: MockerFixture, environment: dict[str, str]
) -> None:
    mocker.patch.dict(
        os.environ,
        environment
        | {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"},
    )
    exporter = InMemorySpanExporter()
    mocker.patch("renamarr.telemetry.OTLPSpanExporter", return_value=exporter)
    telemetry = Telemetry()
    with telemetry.workflow("sonarr", "test").operation("scan", "run"):
        pass
    telemetry.shutdown()
    assert (
        exporter.get_finished_spans()[0].resource.attributes["service.name"] == "custom"
    )


def test_partial_initialization_failure_uninstruments_http(
    mocker: MockerFixture,
) -> None:
    from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor

    mocker.patch.dict(
        os.environ,
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"},
    )
    mocker.patch(
        "renamarr.telemetry.OTLPSpanExporter", return_value=InMemorySpanExporter()
    )
    mocker.patch(
        "renamarr.telemetry.ThreadingInstrumentor.instrument",
        side_effect=RuntimeError("setup"),
    )
    telemetry = Telemetry()
    assert not URLLib3Instrumentor().is_instrumented_by_opentelemetry
    assert isinstance(telemetry._tracer_provider, trace.NoOpTracerProvider)
    with telemetry.workflow("sonarr", "test").operation("scan", "run"):
        pass
    telemetry.shutdown()


def test_instrumentor_release_failure_does_not_skip_providers(
    mocker: MockerFixture,
) -> None:
    mocker.patch.dict(
        os.environ,
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"},
    )
    mocker.patch(
        "renamarr.telemetry.OTLPSpanExporter", return_value=InMemorySpanExporter()
    )
    telemetry = Telemetry()
    assert isinstance(telemetry._tracer_provider, TracerProvider)
    shutdown = mocker.spy(telemetry._tracer_provider, "shutdown")
    instrumentor = telemetry._instrumentors[-1]
    original_uninstrument = instrumentor.uninstrument
    mocker.patch.object(
        instrumentor, "uninstrument", side_effect=RuntimeError("cleanup")
    )
    telemetry.shutdown()
    original_uninstrument()
    shutdown.assert_called_once_with()


@pytest.mark.parametrize("traces_enabled", [False, True])
def test_http_metrics_keep_instance_context_without_requiring_traces(
    mocker: MockerFixture, traces_enabled: bool
) -> None:
    from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
    from urllib3 import PoolManager
    from urllib3.response import HTTPResponse

    mocker.patch.dict(
        os.environ,
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
            "OTEL_TRACES_EXPORTER": "otlp" if traces_enabled else "none",
        },
    )
    reader = InMemoryMetricReader()
    mocker.patch(
        "renamarr.telemetry.PeriodicExportingMetricReader", return_value=reader
    )
    mocker.patch(
        "renamarr.telemetry.OTLPSpanExporter", return_value=InMemorySpanExporter()
    )
    mocker.patch(
        "urllib3.connectionpool.HTTPConnectionPool._make_request",
        return_value=HTTPResponse(body=b"{}", status=200, preload_content=False),
    )
    telemetry = Telemetry()
    pool = PoolManager()
    try:
        for instance in ("first", "second"):
            with telemetry.workflow("sonarr", instance).span("preview"):
                pool.request("GET", "http://example.test/api/v3/series")
        points = measurements(reader)
        durations = points["http.client.duration"]
        assert {point.attributes["arr.instance"] for point in durations} == {
            "first",
            "second",
        }
        assert all(point.attributes["arr.service"] == "sonarr" for point in durations)
    finally:
        pool.clear()
        telemetry.shutdown()
    assert not URLLib3Instrumentor().is_instrumented_by_opentelemetry


def test_partial_batch_does_not_confirm_unverified_files(
    instruments, mocker: MockerFixture
) -> None:
    workflow, reader, exporter = instruments
    adapter = mocker.Mock(spec=ArrAdapter)
    first = MediaItem(1, "First", "/root/first")
    second = MediaItem(2, "Second", "/root/second")
    candidate_a = FileRenameCandidate(first, (10, 11), "First")
    candidate_b = FileRenameCandidate(second, (20,), "Second")
    adapter.list_media_items.return_value = [first, second]
    adapter.get_file_rename_candidate.side_effect = [
        candidate_a,
        candidate_b,
        None,
        candidate_b,
    ]
    adapter.build_file_rename_batches.return_value = [
        FileRenameBatch((1, 2), (10, 11, 20), "First, Second")
    ]
    adapter.start_file_rename.return_value = 20
    adapter.get_command_status.return_value = CommandStatus(True, True)
    result = Renamarr("test", adapter, rename_folders=True, telemetry=workflow).scan()
    assert result.file_renames == WorkSummary(success=1, failed=1)
    assert result.folder_renames == WorkSummary(skipped=2)
    adapter.move_folder.assert_not_called()
    points = measurements(reader)
    assert points["renamarr.rename.requested"][0].value == 3
    assert points["renamarr.rename.confirmed"][0].value == 2
    assert points["renamarr.operation.count"][0].value == 1
    assert points["renamarr.operation.count"][0].attributes["outcome"] == "failed"
    verification = [
        span
        for span in exporter.get_finished_spans()
        if span.name == "renamarr.verification"
    ]
    assert verification[-1].status.status_code == StatusCode.ERROR
    assert points["renamarr.scan.last_success_timestamp"][0].value == 0


@pytest.mark.parametrize(
    "outcome", ["succeeded", "failed", "timed_out", "status_check_error"]
)
def test_command_metrics_distinguish_failures_from_timeouts(
    instruments, mocker: MockerFixture, outcome: str
) -> None:
    workflow, reader, _ = instruments
    adapter = mocker.Mock(spec=ArrAdapter)
    mocker.patch("renamarr.renamarr.time.sleep")
    mocker.patch(
        "renamarr.renamarr.time.monotonic",
        side_effect=[0, 5] if outcome == "timed_out" else [0, 0, 1],
    )
    if outcome == "status_check_error":
        adapter.get_command_status.side_effect = ArrOperationError("status unavailable")
    elif outcome == "succeeded":
        adapter.get_command_status.side_effect = [
            CommandStatus(False, False),
            CommandStatus(True, True),
        ]
    else:
        adapter.get_command_status.return_value = CommandStatus(
            outcome != "timed_out", False
        )
    renamarr = Renamarr(
        "test",
        adapter,
        command_polling=CommandPollingSettings(5, 1),
        telemetry=workflow,
    )
    if outcome == "succeeded":
        renamarr._wait_for_command(17, "rename", "file_rename")
    else:
        with pytest.raises(ArrOperationError):
            renamarr._wait_for_command(17, "rename", "file_rename")
    points = measurements(reader)
    assert points["renamarr.command.count"][0].value == 1
    assert points["renamarr.command.count"][0].attributes["outcome"] == outcome
    assert points["renamarr.command.polls"][0].value == (
        2 if outcome == "succeeded" else 1
    )


def test_exporter_exception_does_not_escape_workflow(mocker: MockerFixture) -> None:
    mocker.patch.dict(
        os.environ,
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"},
    )
    exporter = InMemorySpanExporter()
    mocker.patch.object(
        exporter, "export", side_effect=RuntimeError("collector unavailable")
    )
    mocker.patch("renamarr.telemetry.OTLPSpanExporter", return_value=exporter)
    telemetry = Telemetry()
    with telemetry.workflow("sonarr", "test").operation("scan", "run"):
        pass
    telemetry.shutdown()
