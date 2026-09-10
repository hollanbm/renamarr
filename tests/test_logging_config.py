import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span
from pytest_mock import MockerFixture
from structlog.contextvars import bound_contextvars
from structlog.stdlib import get_logger

from renamarr.logging_config import LoggingConfigurator
from renamarr.telemetry import Telemetry

logger = get_logger("renamarr.config_test")
type ConfigureLogging = Callable[[dict[str, str]], LoggingConfigurator]


@pytest.fixture
def output(mocker: MockerFixture) -> StringIO:
    stream = StringIO()
    mocker.patch("renamarr.logging_config.sys", mocker.Mock(stdout=stream))
    return stream


@pytest.fixture
def configure_logging(
    output: StringIO, tmp_path: Path, mocker: MockerFixture
) -> Iterator[ConfigureLogging]:
    mocker.patch.dict(os.environ, {"LOG_DIR": str(tmp_path)}, clear=True)
    configurations: list[LoggingConfigurator] = []

    def configure(environment: dict[str, str]) -> LoggingConfigurator:
        mocker.patch.dict(os.environ, environment)
        configurator = LoggingConfigurator()
        configurations.append(configurator)
        configurator.configure_stdout()
        return configurator

    yield configure
    for configurator in reversed(configurations):
        configurator.shutdown()


@pytest.mark.parametrize("log_format", ["text", "JSON"])
@pytest.mark.parametrize("level", ["INFO", "debug"])
def test_output_preserves_context_types_levels_and_debug_callsite(
    log_format: str, level: str, configure_logging: ConfigureLogging, output: StringIO
) -> None:
    configure_logging({"LOG_FORMAT": log_format, "LOG_LEVEL": level})
    logger.info("Starting Renamarr")
    with (
        bound_contextvars(arr_type="sonarr", instance="shows"),
        bound_contextvars(item='Example "title"\nnext line'),
    ):
        logger.info("Renamed", renamed_count=12, successful=True)
    logger.debug("Debug detail")
    third_party = logging.getLogger("some_dependency")
    third_party.info("Hidden dependency info")
    third_party.warning("Dependency warning")
    result = output.getvalue()

    assert "Starting Renamarr" in result
    assert "Hidden dependency info" not in result
    assert "Dependency warning" in result
    assert ("Debug detail" in result) is (level == "debug")
    assert "\x1b[" not in result
    assert ("func_name" in result) is (level == "debug")
    if log_format == "JSON":
        records = [json.loads(line) for line in result.splitlines()]
        event = records[1]
        assert event["renamed_count"] == 12
        assert event["successful"] is True
        assert event["item"] == 'Example "title"\nnext line'
        assert event["arr_type"] == "sonarr"
        assert "service" not in event
        assert event["instance"] == "shows"
        assert event["logger"] == "renamarr.config_test"
        assert event["level"] == "info"
        assert event["timestamp"].endswith("Z")
        assert "item" not in records[0]
        assert "_record" not in event
        if level == "debug":
            assert event["module"] == "test_logging_config"
            assert event["func_name"] == (
                "test_output_preserves_context_types_levels_and_debug_callsite"
            )
            assert isinstance(event["lineno"], int)
    else:
        assert "renamed_count=12" in result
        assert "successful=True" in result
        assert "arr_type=sonarr" in result


@pytest.mark.parametrize("log_format", ["text", "json"])
def test_local_exceptions_do_not_dump_locals(
    log_format: str, configure_logging: ConfigureLogging, output: StringIO
) -> None:
    configure_logging({"LOG_FORMAT": log_format})
    private_value = "private-value-not-for-logs"
    try:
        raise ValueError("rename failed")
    except ValueError:
        logger.exception("Failure")

    result = output.getvalue()
    assert "ValueError: rename failed" in result
    assert private_value not in result
    if log_format == "json":
        assert "Traceback" in json.loads(result)["exception"]


@pytest.mark.parametrize("log_format", ["text", "json"])
def test_files_are_isolated_by_arr_type_and_instance_and_never_colored(
    log_format: str,
    configure_logging: ConfigureLogging,
    output: StringIO,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(output, "isatty", return_value=True)
    configurator = configure_logging({"LOG_FORMAT": log_format})
    for arr_type in ("sonarr", "radarr"):
        assert configurator.configure_instance_file(arr_type, "shared")
    assert configurator.configure_instance_file("sonarr", "shared")
    with bound_contextvars(arr_type="sonarr", instance="shared", item="Example"):
        logger.info("Series event", count=3)
        logging.getLogger("some_dependency").warning("Scoped dependency warning")
    with bound_contextvars(arr_type="radarr", instance="shared"):
        logger.info("Movie event")
    with bound_contextvars(arr_type="sonarr", instance="other"):
        logger.info("Different instance")
    logger.info("Unbound event")

    series = (tmp_path / "sonarr" / "shared.log").read_text()
    movies = (tmp_path / "radarr" / "shared.log").read_text()
    assert series.count("Series event") == 1
    assert "Scoped dependency warning" in series
    assert "Movie event" not in series
    assert "Series event" not in movies
    assert "Movie event" in movies
    assert "Different instance" not in series + movies
    assert "Unbound event" not in series + movies
    assert "\x1b[" not in series + movies
    assert ("\x1b[" in output.getvalue()) is (log_format == "text")
    if log_format == "json":
        event, dependency = [json.loads(line) for line in series.splitlines()]
        assert event["count"] == 3
        assert event["item"] == dependency["item"] == "Example"


@pytest.mark.parametrize("rotation", ["00:00", "12:00"])
def test_daily_rotation_cleans_expired_archives_by_age_without_touching_other_files(
    rotation: str,
    configure_logging: ConfigureLogging,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    clock = [time.mktime((2026, 1, 15, int(rotation[:2]), 0, 0, 0, 0, -1)) - 60]
    mocker.patch("logging.handlers.time.time", side_effect=lambda: clock[0])
    configurator = configure_logging({"LOG_ROTATION": rotation})
    path = tmp_path / "sonarr" / "shows.v1.log"
    path.parent.mkdir()
    path.write_text("Previous event\n")
    os.utime(path, (clock[0], clock[0]))
    assert configurator.configure_instance_file("sonarr", "shows.v1")
    expired = [
        "shows.v1.log.2026-01-01",
        "shows.v1.2026-01-02_00-00-00_000000.log",
        "shows.v1.2026-01-02_00-00-00_000000.1.log",
    ]
    preserved = [
        "shows.v1.log.2026-01-13",
        "showsXv1.log.2026-01-01",
        "shows.v1.other.log.2026-01-01",
        "notes.txt",
    ]
    for name in expired + preserved:
        archive = path.parent / name
        archive.write_text("archive")
        age = 1 if name == preserved[0] else 8
        modified = clock[0] - timedelta(days=age).total_seconds()
        os.utime(archive, (modified, modified))
    matching_directory = path.parent / "shows.v1.log.2025-12-01"
    matching_directory.mkdir()
    for index in range(10):
        (path.parent / f"shows.v1.2026-01-14_01-00-00_{index:06d}.log").write_text(
            "recent archive"
        )
    with bound_contextvars(arr_type="sonarr", instance="shows.v1"):
        logger.info("Before rotation")
        assert "Before rotation" in path.read_text()
        clock[0] += 120
        logger.info("After rotation")

    assert "After rotation" in path.read_text()
    assert "Before rotation" not in path.read_text()
    for name in expired:
        assert not (path.parent / name).exists()
    for name in preserved:
        assert (path.parent / name).is_file()
    assert matching_directory.is_dir()
    assert len(list(path.parent.glob("shows.v1.2026-01-14_*.log"))) == 10
    assert any(
        "Before rotation" in archive.read_text()
        for archive in path.parent.glob("shows.v1.log.*")
        if archive.is_file()
    )


def test_restart_rotates_an_existing_file_and_honors_custom_retention(
    configure_logging: ConfigureLogging, tmp_path: Path, mocker: MockerFixture
) -> None:
    now = time.mktime((2026, 1, 20, 13, 0, 0, 0, 0, -1))
    mocker.patch("logging.handlers.time.time", return_value=now)
    path = tmp_path / "sonarr" / "shows.log"
    path.parent.mkdir()
    path.write_text("Before restart\n")
    modified = now - 86400
    os.utime(path, (modified, modified))
    archive = path.parent / "shows.log.2026-01-10"
    archive.write_text("Keep ten-day-old archive")
    os.utime(archive, (now - 10 * 86400, now - 10 * 86400))
    configurator = configure_logging(
        {"LOG_ROTATION": "12:00", "LOG_RETENTION": "14 days"}
    )
    assert configurator.configure_instance_file("sonarr", "shows")
    with bound_contextvars(arr_type="sonarr", instance="shows"):
        logger.info("After restart")

    assert "Before restart" not in path.read_text()
    assert "After restart" in path.read_text()
    assert archive.is_file()


@pytest.mark.parametrize(
    "environment",
    [
        {"LOG_LEVEL": "invalid"},
        {"LOG_LEVEL": "NOTSET"},
        {"LOG_FORMAT": "logfmt"},
        {"LOG_ROTATION": "24:00"},
        {"LOG_ROTATION": "10 MB"},
        {"LOG_RETENTION": "0 days"},
        {"LOG_RETENTION": "1 week"},
    ],
)
def test_invalid_logging_settings_are_rejected(
    environment: dict[str, str], configure_logging: ConfigureLogging
) -> None:
    with pytest.raises(ValueError, match=next(iter(environment))):
        configurator = configure_logging(environment)
        configurator.configure_instance_file("sonarr", "shows")


def test_file_defaults_use_logs_directory_and_singular_retention_is_accepted(
    configure_logging: ConfigureLogging, mocker: MockerFixture
) -> None:
    configurator = configure_logging({"LOG_RETENTION": "1 day"})
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch("renamarr.logging_config.Path.mkdir")
    handler_factory = mocker.patch(
        "renamarr.logging_config._DailyFileHandler", return_value=logging.NullHandler()
    )
    assert configurator.configure_instance_file("sonarr", "shows")
    assert handler_factory.call_args.args[0] == Path("/logs/sonarr/shows.log")
    assert handler_factory.call_args.args[2] == 7
    mocker.patch.dict(os.environ, {"LOG_RETENTION": "1 day"})
    assert configurator.configure_instance_file("sonarr", "other")
    assert handler_factory.call_args.args[2] == 1


@pytest.mark.parametrize("failure_point", ["directory", "file"])
def test_unwritable_file_logs_a_contextual_warning_and_keeps_stdout(
    failure_point: str,
    configure_logging: ConfigureLogging,
    output: StringIO,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    configurator = configure_logging({"LOG_FORMAT": "json"})
    target = (
        "renamarr.logging_config.Path.mkdir"
        if failure_point == "directory"
        else "renamarr.logging_config._DailyFileHandler"
    )
    mocker.patch(target, side_effect=PermissionError("read-only directory"))
    assert not configurator.configure_instance_file("sonarr", "shows")
    logger.info("Continuing")
    warning, continuation = [
        json.loads(line) for line in output.getvalue().splitlines()
    ]
    assert warning["level"] == "warning"
    assert warning["arr_type"] == "sonarr"
    assert warning["instance"] == "shows"
    assert warning["path"] == str(tmp_path / "sonarr" / "shows.log")
    assert warning["error"] == "read-only directory"
    assert continuation["event"] == "Continuing"
    assert "arr_type" not in continuation
    assert "instance" not in continuation


def test_stdout_and_otlp_configuration_are_idempotent_and_preserve_raw_events(
    configure_logging: ConfigureLogging, output: StringIO, mocker: MockerFixture
) -> None:
    exporter = InMemoryLogRecordExporter()
    mocker.patch("renamarr.telemetry.OTLPLogExporter", return_value=exporter)
    configurator = configure_logging(
        {"LOG_FORMAT": "json", "OTEL_LOGS_EXPORTER": "otlp"}
    )
    configurator.configure_stdout()
    configurator.configure_otlp()
    configurator.configure_otlp()
    span = NonRecordingSpan(SpanContext(123, 456, False, TraceFlags(1)))
    with use_span(span), bound_contextvars(arr_type="sonarr", instance="shows"):
        try:
            raise ValueError("failure")
        except ValueError:
            logger.exception("Failed", count=2, retried=False)
    configurator.shutdown()
    configurator.shutdown()

    event = json.loads(output.getvalue())
    assert event["trace_id"] == f"{123:032x}"
    assert event["span_id"] == f"{456:016x}"
    assert "ValueError: failure" in event["exception"]
    records = exporter.get_finished_logs()
    assert len(records) == 1
    record = records[0].log_record
    assert record.body == "Failed"
    assert record.trace_id == 123 and record.span_id == 456
    assert record.attributes is not None
    assert record.attributes["count"] == 2
    assert record.attributes["retried"] is False
    assert record.attributes["arr_type"] == "sonarr"
    assert "service" not in record.attributes
    assert record.attributes["exception.type"] == "ValueError"


def test_disabled_otlp_leaves_handlers_unchanged(
    configure_logging: ConfigureLogging,
) -> None:
    configurator = configure_logging({})
    handlers = logging.getLogger().handlers.copy()
    configurator.configure_otlp()
    assert logging.getLogger().handlers == handlers


def test_shutdown_keeps_local_handlers_for_diagnostics_and_closes_them_after_failure(
    configure_logging: ConfigureLogging, output: StringIO, mocker: MockerFixture
) -> None:
    original_handlers = logging.getLogger().handlers.copy()
    configurator = configure_logging({})
    telemetry = mocker.Mock(spec=Telemetry, handler=logging.NullHandler())
    mocker.patch("renamarr.logging_config.configure_telemetry", return_value=telemetry)

    def fail_shutdown() -> None:
        logging.getLogger("opentelemetry").warning("Exporter shutdown failed")
        raise RuntimeError("shutdown failed")

    telemetry.shutdown.side_effect = fail_shutdown
    configurator.configure_otlp()
    with pytest.raises(RuntimeError, match="shutdown failed"):
        configurator.shutdown()
    configurator.shutdown()

    assert "Exporter shutdown failed" in output.getvalue()
    assert logging.getLogger().handlers == original_handlers
    telemetry.shutdown.assert_called_once_with()
