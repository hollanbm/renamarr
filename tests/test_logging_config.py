import os
from contextlib import nullcontext
from sys import stdout
from unittest.mock import ANY

from loguru import logger
from renamarr.logging_config import LoggingConfigurator


class TestLoggingConfigurator:
    def test_configure_stdout_uses_text_logging_when_otel_is_disabled(
        self, mocker
    ) -> None:
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_configure = mocker.patch.object(logger, "configure")
        logger_remove = mocker.patch.object(logger, "remove")
        logger_add = mocker.patch.object(logger, "add")

        LoggingConfigurator().configure_stdout()

        logger_configure.assert_called_once_with(
            extra={
                "service": "",
                "instance": "",
                "item": "",
                "trace_id": "",
                "span_id": "",
            },
            patcher=None,
        )
        logger_remove.assert_called_once_with()
        assert logger_add.call_args.args == (stdout,)
        assert logger_add.call_args.kwargs["format"] == LoggingConfigurator._LOG_FORMAT
        assert logger_add.call_args.kwargs["level"] == "INFO"
        assert "serialize" not in logger_add.call_args.kwargs

    def test_configure_stdout_adds_trace_fields_when_otel_is_enabled(
        self, mocker
    ) -> None:
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=True)
        logger_configure = mocker.patch.object(logger, "configure")
        logger_add = mocker.patch.object(logger, "add")

        LoggingConfigurator().configure_stdout()

        logger_configure.assert_called_once_with(
            extra={
                "service": "",
                "instance": "",
                "item": "",
                "trace_id": "",
                "span_id": "",
            },
            patcher=ANY,
        )
        assert logger_configure.call_args.kwargs["patcher"].__name__ == (
            "enrich_log_record_with_trace"
        )
        logger_format = logger_add.call_args.kwargs["format"]
        assert "trace_id={extra[trace_id]}" in logger_format
        assert "span_id={extra[span_id]}" in logger_format

    def test_configure_stdout_uses_json_logging_when_requested(self, mocker) -> None:
        mocker.patch.dict(os.environ, {"LOG_FORMAT": "json"}, clear=True)
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_add = mocker.patch.object(logger, "add")

        LoggingConfigurator().configure_stdout()

        assert logger_add.call_args.args == (stdout,)
        assert logger_add.call_args.kwargs["level"] == "INFO"
        assert logger_add.call_args.kwargs["serialize"] is True
        assert "format" not in logger_add.call_args.kwargs

    def test_configure_stdout_hides_source_location_by_default(self, mocker) -> None:
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_add = mocker.patch.object(logger, "add")

        LoggingConfigurator().configure_stdout()

        logger_format = logger_add.call_args.kwargs["format"]
        logger_name_format = "<cyan>{name}</cyan>"
        source_location_format = "<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        assert logger_name_format not in logger_format
        assert source_location_format not in logger_format

    def test_configure_stdout_shows_source_location_when_log_level_is_debug(
        self, mocker
    ) -> None:
        mocker.patch.dict(os.environ, {"LOG_LEVEL": "debug"}, clear=True)
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_add = mocker.patch.object(logger, "add")

        LoggingConfigurator().configure_stdout()

        logger_format = logger_add.call_args.kwargs["format"]
        logger_name_format = "<cyan>{name}</cyan>"
        source_location_format = "<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        assert f"{logger_name_format}:{source_location_format}" in logger_format

    def test_configure_instance_file_configures_instance_sink(self, mocker) -> None:
        mocker.patch.dict(
            os.environ,
            {
                "LOG_DIR": "/tmp/renamarr-logs",
                "LOG_LEVEL": "DEBUG",
                "LOG_RETENTION": "14 days",
                "LOG_ROTATION": "12:00",
            },
            clear=True,
        )
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_add = mocker.patch.object(logger, "add")

        configured = LoggingConfigurator().configure_instance_file("sonarr", "sonarr")

        assert configured
        assert logger_add.call_args.args == ("/tmp/renamarr-logs/sonarr/sonarr.log",)
        assert logger_add.call_args.kwargs["format"]
        assert logger_add.call_args.kwargs["level"] == "DEBUG"
        assert logger_add.call_args.kwargs["rotation"] == "12:00"
        assert logger_add.call_args.kwargs["retention"] == "14 days"

        filter_fn = logger_add.call_args.kwargs["filter"]
        assert filter_fn({"extra": {"service": "sonarr", "instance": "sonarr"}})
        assert not filter_fn({"extra": {"service": "radarr", "instance": "sonarr"}})
        assert not filter_fn({"extra": {"service": "sonarr", "instance": "sonarr1"}})
        assert not filter_fn({"extra": {}})

    def test_configure_instance_file_warns_when_sink_setup_fails(
        self, mock_loguru_warning, mocker
    ) -> None:
        mocker.patch.dict(os.environ, {"LOG_DIR": "/tmp/renamarr-logs"}, clear=True)
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_add = mocker.patch.object(logger, "add")
        logger_add.side_effect = PermissionError("read-only file system")
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )

        configured = LoggingConfigurator().configure_instance_file("radarr", "radarr")

        assert not configured
        contextualize.assert_called_once_with(service="radarr", instance="radarr")
        mock_loguru_warning.assert_any_call(
            "Unable to write logs to '/tmp/renamarr-logs/radarr/radarr.log'; continuing with stdout logging only."
        )
        assert isinstance(
            mock_loguru_warning.call_args_list[-1].args[0], PermissionError
        )

    def test_configure_instance_file_uses_json_sink_when_requested(
        self, mocker
    ) -> None:
        mocker.patch.dict(
            os.environ,
            {"LOG_FORMAT": "json", "LOG_DIR": "/tmp/renamarr-logs"},
            clear=True,
        )
        mocker.patch("renamarr.logging_config.is_otel_enabled", return_value=False)
        logger_add = mocker.patch.object(logger, "add")

        configured = LoggingConfigurator().configure_instance_file("radarr", "radarr")

        assert configured
        assert logger_add.call_args.args == ("/tmp/renamarr-logs/radarr/radarr.log",)
        assert logger_add.call_args.kwargs["serialize"] is True
        assert "format" not in logger_add.call_args.kwargs
