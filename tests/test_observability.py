import os

from renamarr.observability import (
    DEFAULT_SERVICE_NAME,
    OTEL_ENABLED_ENV_VAR,
    DisabledObservability,
    OpenTelemetryObservability,
    configure_observability,
    enrich_log_record_with_trace,
    get_log_trace_context,
    get_observability,
)


def test_disabled_observability_noops() -> None:
    observability = DisabledObservability()

    with observability.start_span("span") as span:
        assert span is None

    observability.record_job_started("sonarr", "sonarr", "renamarr", 1.0)
    observability.record_job("sonarr", "sonarr", "renamarr", "success", 1.0)
    observability.record_operation_scanned_items("sonarr", "sonarr", "rename", 1)
    observability.record_operation_candidate_items("sonarr", "sonarr", "rename", 1)
    observability.record_operation_run("sonarr", "sonarr", "rename", "noop")
    observability.record_operation_items("sonarr", "sonarr", "rename", "accepted", 1)
    observability.record_arr_command(
        "sonarr", "sonarr", "RescanSeries", "successful", 1.0
    )
    observability.force_flush()
    observability.shutdown()


def test_configure_observability_defaults_to_disabled(mocker) -> None:
    mocker.patch.dict(os.environ, {}, clear=True)
    build = mocker.patch("renamarr.observability.OpenTelemetryObservability.build")

    observability = configure_observability()

    assert isinstance(observability, DisabledObservability)
    assert get_observability() is observability
    build.assert_not_called()


def test_configure_observability_builds_otel_when_enabled(mocker) -> None:
    otel_observability = mocker.Mock()
    build = mocker.patch(
        "renamarr.observability.OpenTelemetryObservability.build",
        return_value=otel_observability,
    )
    mocker.patch.dict(os.environ, {OTEL_ENABLED_ENV_VAR: "TRUE"})

    observability = configure_observability()

    assert observability is otel_observability
    assert get_observability() is observability
    build.assert_called_once_with()


def test_get_log_trace_context_returns_active_span_identifiers(mocker) -> None:
    span_context = mocker.Mock(
        is_valid=True,
        trace_id=int("1234567890abcdef1234567890abcdef", 16),
        span_id=int("1234567890abcdef", 16),
    )
    span = mocker.Mock()
    span.get_span_context.return_value = span_context
    mocker.patch("renamarr.observability.trace.get_current_span", return_value=span)

    assert get_log_trace_context() == {
        "trace_id": "1234567890abcdef1234567890abcdef",
        "span_id": "1234567890abcdef",
    }


def test_get_log_trace_context_returns_empty_values_without_valid_span(mocker) -> None:
    span_context = mocker.Mock(is_valid=False)
    span = mocker.Mock()
    span.get_span_context.return_value = span_context
    mocker.patch("renamarr.observability.trace.get_current_span", return_value=span)

    assert get_log_trace_context() == {"trace_id": "", "span_id": ""}


def test_enrich_log_record_with_trace_updates_loguru_extra(mocker) -> None:
    mocker.patch(
        "renamarr.observability.get_log_trace_context",
        return_value={"trace_id": "trace", "span_id": "span"},
    )
    record: dict[str, object] = {"extra": {"instance": "sonarr"}}

    enrich_log_record_with_trace(record)

    assert record["extra"] == {
        "instance": "sonarr",
        "trace_id": "trace",
        "span_id": "span",
    }


def test_enrich_log_record_with_trace_ignores_missing_extra(mocker) -> None:
    get_log_trace_context = mocker.patch("renamarr.observability.get_log_trace_context")

    enrich_log_record_with_trace({})

    get_log_trace_context.assert_not_called()


def test_open_telemetry_observability_records_metrics_and_spans(mocker) -> None:
    tracer = mocker.Mock()
    span_context = mocker.MagicMock()
    tracer.start_as_current_span.return_value = span_context
    tracer_provider = mocker.Mock()
    tracer_provider.get_tracer.return_value = tracer
    meter = mocker.Mock()
    job_runs = mocker.Mock()
    operation_runs = mocker.Mock()
    operation_items = mocker.Mock()
    operation_scanned_items = mocker.Mock()
    operation_candidate_items = mocker.Mock()
    arr_command_runs = mocker.Mock()
    meter.create_counter.side_effect = [
        job_runs,
        operation_runs,
        operation_items,
        operation_scanned_items,
        operation_candidate_items,
        arr_command_runs,
    ]
    job_duration = mocker.Mock()
    arr_command_duration = mocker.Mock()
    meter.create_histogram.side_effect = [job_duration, arr_command_duration]
    job_last_started = mocker.Mock()
    job_last_completed = mocker.Mock()
    job_last_success = mocker.Mock()
    meter.create_gauge.side_effect = [
        job_last_started,
        job_last_completed,
        job_last_success,
    ]
    meter_provider = mocker.Mock()
    meter_provider.get_meter.return_value = meter
    requests_instrumentor = mocker.Mock()
    mocker.patch("renamarr.observability.time.time", return_value=100.0)

    observability = OpenTelemetryObservability(
        tracer_provider,
        meter_provider,
        requests_instrumentor,
    )

    assert meter.create_counter.call_args_list[0].args == ("renamarr.job.runs",)
    assert meter.create_counter.call_args_list[1].args == ("renamarr.operation.runs",)
    assert meter.create_counter.call_args_list[2].args == ("renamarr.operation.items",)
    assert meter.create_counter.call_args_list[3].args == (
        "renamarr.operation.scanned.items",
    )
    assert meter.create_counter.call_args_list[4].args == (
        "renamarr.operation.candidate.items",
    )
    assert meter.create_counter.call_args_list[5].args == ("renamarr.arr.command.runs",)

    returned_context = observability.start_span("span", {"service": "sonarr"})
    observability.record_job_started("sonarr", "tv", "renamarr", 99.0)
    observability.record_operation_scanned_items("radarr", "radarr-4k", "rename", 3)
    observability.record_operation_candidate_items("radarr", "radarr-4k", "rename", 2)
    observability.record_operation_run("radarr", "radarr-4k", "folder_rename", "failed")
    observability.record_operation_items(
        "radarr",
        "radarr-4k",
        "folder_rename",
        "failed",
        2,
    )
    observability.record_arr_command(
        "radarr",
        "radarr-4k",
        "RefreshMovie",
        "successful",
        12.5,
    )
    observability.record_job("sonarr", "tv", "renamarr", "success", 1.25)
    observability.force_flush()
    observability.shutdown()

    assert returned_context is span_context
    tracer_provider.get_tracer.assert_called_once_with(DEFAULT_SERVICE_NAME)
    meter_provider.get_meter.assert_called_once_with(DEFAULT_SERVICE_NAME)
    tracer.start_as_current_span.assert_called_once_with(
        "span", attributes={"service": "sonarr"}
    )
    job_last_started.set.assert_called_once_with(
        99.0,
        attributes={"service": "sonarr", "name": "tv", "job": "renamarr"},
    )
    operation_scanned_items.add.assert_called_once_with(
        3,
        attributes={"service": "radarr", "name": "radarr-4k", "operation": "rename"},
    )
    operation_candidate_items.add.assert_called_once_with(
        2,
        attributes={"service": "radarr", "name": "radarr-4k", "operation": "rename"},
    )
    operation_runs.add.assert_called_once_with(
        1,
        attributes={
            "service": "radarr",
            "name": "radarr-4k",
            "operation": "folder_rename",
            "result": "failed",
        },
    )
    operation_items.add.assert_called_once_with(
        2,
        attributes={
            "service": "radarr",
            "name": "radarr-4k",
            "operation": "folder_rename",
            "result": "failed",
        },
    )
    arr_command_runs.add.assert_called_once_with(
        1,
        attributes={
            "service": "radarr",
            "name": "radarr-4k",
            "command": "RefreshMovie",
            "result": "successful",
        },
    )
    arr_command_duration.record.assert_called_once_with(
        12.5,
        attributes={
            "service": "radarr",
            "name": "radarr-4k",
            "command": "RefreshMovie",
            "result": "successful",
        },
    )
    job_runs.add.assert_called_once_with(
        1,
        attributes={
            "service": "sonarr",
            "name": "tv",
            "job": "renamarr",
            "result": "success",
        },
    )
    job_last_completed.set.assert_called_once_with(
        100.0,
        attributes={"service": "sonarr", "name": "tv", "job": "renamarr"},
    )
    job_last_success.set.assert_called_once_with(
        100.0,
        attributes={"service": "sonarr", "name": "tv", "job": "renamarr"},
    )
    job_duration.record.assert_called_once_with(
        1.25,
        attributes={
            "service": "sonarr",
            "name": "tv",
            "job": "renamarr",
            "result": "success",
        },
    )
    assert tracer_provider.force_flush.call_count == 2
    assert meter_provider.force_flush.call_count == 2
    requests_instrumentor.uninstrument.assert_called_once_with()
    tracer_provider.shutdown.assert_called_once_with()
    meter_provider.shutdown.assert_called_once_with()


def test_open_telemetry_observability_does_not_record_success_timestamp_for_failed_job(
    mocker,
) -> None:
    tracer_provider = mocker.Mock()
    meter = mocker.Mock()
    meter.create_counter.side_effect = [mocker.Mock() for _ in range(6)]
    meter.create_histogram.side_effect = [mocker.Mock() for _ in range(2)]
    job_last_started = mocker.Mock()
    job_last_completed = mocker.Mock()
    job_last_success = mocker.Mock()
    meter.create_gauge.side_effect = [
        job_last_started,
        job_last_completed,
        job_last_success,
    ]
    meter_provider = mocker.Mock()
    meter_provider.get_meter.return_value = meter
    requests_instrumentor = mocker.Mock()
    mocker.patch("renamarr.observability.time.time", return_value=100.0)
    observability = OpenTelemetryObservability(
        tracer_provider,
        meter_provider,
        requests_instrumentor,
    )

    observability.record_job("sonarr", "tv", "renamarr", "failed", 1.25)

    job_last_completed.set.assert_called_once_with(
        100.0,
        attributes={"service": "sonarr", "name": "tv", "job": "renamarr"},
    )
    job_last_success.set.assert_not_called()


def test_open_telemetry_build_uses_standard_otel_configuration(mocker) -> None:
    resource = mocker.Mock()
    resource_create = mocker.patch(
        "renamarr.observability.Resource.create",
        return_value=resource,
    )
    span_exporter = mocker.Mock()
    span_exporter_class = mocker.patch(
        "renamarr.observability.OTLPSpanExporter",
        return_value=span_exporter,
    )
    span_processor = mocker.Mock()
    span_processor_class = mocker.patch(
        "renamarr.observability.BatchSpanProcessor",
        return_value=span_processor,
    )
    tracer = mocker.Mock()
    tracer_provider = mocker.Mock()
    tracer_provider.get_tracer.return_value = tracer
    tracer_provider_class = mocker.patch(
        "renamarr.observability.TracerProvider",
        return_value=tracer_provider,
    )
    metric_exporter = mocker.Mock()
    metric_exporter_class = mocker.patch(
        "renamarr.observability.OTLPMetricExporter",
        return_value=metric_exporter,
    )
    metric_reader = mocker.Mock()
    metric_reader_class = mocker.patch(
        "renamarr.observability.PeriodicExportingMetricReader",
        return_value=metric_reader,
    )
    meter = mocker.Mock()
    meter.create_counter.side_effect = [mocker.Mock() for _ in range(6)]
    meter.create_histogram.side_effect = [mocker.Mock() for _ in range(2)]
    meter.create_gauge.side_effect = [mocker.Mock() for _ in range(3)]
    meter_provider = mocker.Mock()
    meter_provider.get_meter.return_value = meter
    meter_provider_class = mocker.patch(
        "renamarr.observability.MeterProvider",
        return_value=meter_provider,
    )
    requests_instrumentor = mocker.Mock()
    requests_instrumentor_class = mocker.patch(
        "renamarr.observability.RequestsInstrumentor",
        return_value=requests_instrumentor,
    )
    mocker.patch.dict(os.environ, {"OTEL_SERVICE_NAME": "custom-renamarr"})

    observability = OpenTelemetryObservability.build()

    assert isinstance(observability, OpenTelemetryObservability)
    resource_create.assert_called_once_with({"service.name": "custom-renamarr"})
    tracer_provider_class.assert_called_once_with(
        resource=resource,
        shutdown_on_exit=False,
    )
    span_exporter_class.assert_called_once_with()
    span_processor_class.assert_called_once_with(span_exporter)
    tracer_provider.add_span_processor.assert_called_once_with(span_processor)
    metric_exporter_class.assert_called_once_with()
    metric_reader_class.assert_called_once_with(metric_exporter)
    meter_provider_class.assert_called_once_with(
        resource=resource,
        metric_readers=[metric_reader],
        shutdown_on_exit=False,
    )
    requests_instrumentor_class.assert_called_once_with()
    requests_instrumentor.instrument.assert_called_once_with(
        tracer_provider=tracer_provider
    )
