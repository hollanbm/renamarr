import os
from collections.abc import Iterator
from contextlib import nullcontext
from io import StringIO
from pathlib import Path
from sys import stderr, stdout

import pytest
from loguru import logger
from pytest_mock import MockerFixture

from renamarr.logging_config import LoggingConfigurator


@pytest.fixture
def restore_default_logger() -> Iterator[None]:
    yield
    logger.remove()
    logger.configure(extra={}, patcher=None)
    logger.add(stderr)


class TestLoggingConfigurator:
    @pytest.mark.parametrize(
        ("log_level", "expected_format"),
        [
            ("INFO", LoggingConfigurator._LOG_FORMAT),
            ("debug", LoggingConfigurator._DEBUG_LOG_FORMAT),
        ],
    )
    def test_configure_stdout(
        self,
        log_level: str,
        expected_format: str,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.dict(os.environ, {"LOG_LEVEL": log_level}, clear=True)
        logger_configure = mocker.patch.object(logger, "configure")
        logger_remove = mocker.patch.object(logger, "remove")
        logger_add = mocker.patch.object(logger, "add")

        LoggingConfigurator().configure_stdout()

        logger_configure.assert_called_once()
        assert logger_configure.call_args.kwargs["extra"] == {
            "instance": "",
            "item": "",
        }
        patcher = logger_configure.call_args.kwargs["patcher"]
        record_without_item = {"extra": {"item": ""}}
        record_with_item = {"extra": {"item": "Example"}}
        patcher(record_without_item)
        patcher(record_with_item)
        assert record_without_item["extra"]["item_context"] == ""
        assert record_with_item["extra"]["item_context"] == "Example | "
        logger_remove.assert_called_once_with()
        logger_add.assert_called_once_with(
            stdout,
            format=expected_format,
            level=log_level,
        )

    @pytest.mark.parametrize("log_level", ["INFO", "DEBUG"])
    def test_text_format_only_includes_item_column_when_item_is_set(
        self,
        log_level: str,
        restore_default_logger: None,
        mocker: MockerFixture,
    ) -> None:
        output = StringIO()
        mocker.patch("renamarr.logging_config.stdout", output)
        mocker.patch.dict(os.environ, {"LOG_LEVEL": log_level}, clear=True)
        LoggingConfigurator().configure_stdout()

        with logger.contextualize(instance="sonarr"):
            logger.info("Starting Renamarr")
            with logger.contextualize(item="Example"):
                logger.info("No files need renaming")

        instance_message, item_message = output.getvalue().splitlines()
        assert instance_message.endswith(" | sonarr | Starting Renamarr")
        assert item_message.endswith(" | sonarr | Example | No files need renaming")
        assert " | sonarr |  | " not in instance_message

    def test_instance_file_emits_without_stdout_configuration(
        self,
        tmp_path: Path,
        restore_default_logger: None,
        mocker: MockerFixture,
    ) -> None:
        logger.remove()
        mocker.patch.dict(os.environ, {"LOG_DIR": str(tmp_path)}, clear=True)

        configured = LoggingConfigurator().configure_instance_file("sonarr", "shows")
        with logger.contextualize(service="sonarr", instance="shows"):
            logger.info("Starting Renamarr")

        assert configured
        output = (tmp_path / "sonarr" / "shows.log").read_text(encoding="utf-8")
        assert output.rstrip().endswith(" | shows | Starting Renamarr")
        assert " | shows |  | " not in output

    def test_configure_instance_file_uses_environment_configuration(
        self, mocker: MockerFixture
    ) -> None:
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
        logger_configure = mocker.patch.object(logger, "configure")
        logger_add = mocker.patch.object(logger, "add")

        configured = LoggingConfigurator().configure_instance_file("sonarr", "shows")

        assert configured
        logger_configure.assert_called_once()
        logger_add.assert_called_once()
        assert logger_add.call_args.args == ("/tmp/renamarr-logs/sonarr/shows.log",)
        assert logger_add.call_args.kwargs["format"] == (
            LoggingConfigurator._DEBUG_LOG_FORMAT
        )
        assert logger_add.call_args.kwargs["level"] == "DEBUG"
        assert logger_add.call_args.kwargs["rotation"] == "12:00"
        assert logger_add.call_args.kwargs["retention"] == "14 days"

        instance_filter = logger_add.call_args.kwargs["filter"]
        assert instance_filter({"extra": {"service": "sonarr", "instance": "shows"}})
        assert not instance_filter(
            {"extra": {"service": "radarr", "instance": "shows"}}
        )
        assert not instance_filter(
            {"extra": {"service": "sonarr", "instance": "movies"}}
        )
        assert not instance_filter({"extra": {}})

    def test_configure_instance_file_uses_defaults(self, mocker: MockerFixture) -> None:
        mocker.patch.dict(os.environ, {}, clear=True)
        logger_configure = mocker.patch.object(logger, "configure")
        logger_add = mocker.patch.object(logger, "add")

        configured = LoggingConfigurator().configure_instance_file("radarr", "movies")

        assert configured
        logger_configure.assert_called_once()
        logger_add.assert_called_once()
        assert logger_add.call_args.args == ("/logs/radarr/movies.log",)
        assert logger_add.call_args.kwargs["format"] == LoggingConfigurator._LOG_FORMAT
        assert logger_add.call_args.kwargs["level"] == "INFO"
        assert logger_add.call_args.kwargs["rotation"] == "00:00"
        assert logger_add.call_args.kwargs["retention"] == "7 days"

    def test_configure_instance_file_warns_when_sink_setup_fails(
        self, mock_loguru_warning, mocker: MockerFixture
    ) -> None:
        mocker.patch.dict(
            os.environ,
            {"LOG_DIR": "/tmp/renamarr-logs"},
            clear=True,
        )
        logger_configure = mocker.patch.object(logger, "configure")
        logger_add = mocker.patch.object(
            logger,
            "add",
            side_effect=PermissionError("read-only file system"),
        )
        contextualize = mocker.patch.object(
            logger,
            "contextualize",
            return_value=nullcontext(),
        )

        configured = LoggingConfigurator().configure_instance_file("radarr", "movies")

        assert not configured
        logger_configure.assert_called_once()
        logger_add.assert_called_once()
        contextualize.assert_called_once_with(service="radarr", instance="movies")
        mock_loguru_warning.assert_any_call(
            "Unable to write logs to '/tmp/renamarr-logs/radarr/movies.log'; continuing with stdout logging only."
        )
        assert isinstance(
            mock_loguru_warning.call_args_list[-1].args[0], PermissionError
        )
