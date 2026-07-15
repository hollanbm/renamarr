import os
from contextlib import nullcontext
from pathlib import Path
from typing import Generator
from unittest.mock import PropertyMock

import pytest
from loguru import logger
from config_schema import CONFIG_SCHEMA
from main import Main
from pycliarr.api import CliArrError
from pyconfigparser import ConfigError, ConfigFileNotFoundError, configparser
from schedule import Job, Scheduler

# disable config caching
configparser.hold_an_instance = False


class TestMain:
    @pytest.fixture
    def enable_scheduler(self, mocker) -> Generator:
        """
        Allows scheduler loop to enter, exactly one time, and then exit
        """
        mocker.patch("main.sleep").return_value = None
        Main.RUN_SCHEDULER = PropertyMock(side_effect=[True, False])
        yield
        Main.RUN_SCHEDULER = True

    @pytest.fixture
    def external_cron(self, mocker) -> Generator:
        os.environ["EXTERNAL_CRON"] = "TRUE"
        yield
        del os.environ["EXTERNAL_CRON"]

    @pytest.fixture
    def log_dir(self) -> Generator:
        os.environ["LOG_DIR"] = "/tmp/renamarr-logs"
        yield
        del os.environ["LOG_DIR"]

    @pytest.fixture
    def log_retention(self) -> Generator:
        os.environ["LOG_RETENTION"] = "14 days"
        yield
        del os.environ["LOG_RETENTION"]

    @pytest.fixture
    def log_rotation(self) -> Generator:
        os.environ["LOG_ROTATION"] = "12:00"
        yield
        del os.environ["LOG_ROTATION"]

    @pytest.fixture
    def log_level(self) -> Generator:
        os.environ["LOG_LEVEL"] = "DEBUG"
        yield
        del os.environ["LOG_LEVEL"]

    @pytest.fixture
    def config_dir(self) -> Generator:
        os.environ["CONFIG_DIR"] = "tests/fixtures"
        yield
        del os.environ["CONFIG_DIR"]

    @pytest.fixture
    def config(self) -> Generator:
        """
        Disable scheduler loop for the majority of tests
        """
        Main.RUN_SCHEDULER = False
        yield configparser.get_config(
            CONFIG_SCHEMA,
            config_dir="tests/fixtures",
            file_name="disabled.yml",
        )

    def test_all_disabled(self, config, mocker) -> None:
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config

        series_scanner = mocker.patch("main.SonarrSeriesScanner")
        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")
        radarr_renamarr = mocker.patch("main.RadarrRenamarr")
        job = mocker.patch.object(Job, "do")

        Main().start()

        series_scanner.assert_not_called()
        sonarr_renamarr.assert_not_called()
        radarr_renamarr.assert_not_called()
        job.assert_not_called()

    def test_sonarr_series_scanner_scan(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        sonarr_series_scanner = mocker.patch("main.SonarrSeriesScanner")

        Main().start()

        sonarr_series_scanner.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            hours_before_air=config.sonarr[0].series_scanner.hours_before_air,
        )
        sonarr_series_scanner.return_value.scan.assert_called_once_with()

    def test_start_uses_config_dir_env_var(self, config_dir, mocker) -> None:
        config = configparser.get_config(
            CONFIG_SCHEMA,
            config_dir="tests/fixtures",
            file_name="disabled.yml",
        )
        set_directory = mocker.patch("main.set_directory")
        get_config = mocker.patch("pyconfigparser.configparser.get_config")
        get_config.return_value = config
        mocker.patch.object(Job, "do")

        Main().start()

        set_directory.assert_called_once_with("tests/fixtures")
        get_config.assert_called_once_with(CONFIG_SCHEMA)

    def test_start_supports_absolute_config_dir(self, tmp_path, mocker):
        config_directory = tmp_path / "config"
        config_directory.mkdir()
        config_path = config_directory / "config.yml"
        config_path.write_text(
            Path("tests/fixtures/disabled.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        os.environ["CONFIG_DIR"] = str(tmp_path)
        mocker.patch.object(Job, "do")
        try:
            Main().start()
        finally:
            del os.environ["CONFIG_DIR"]

    def test_init_uses_log_level_env_var(self, log_level, mocker) -> None:
        logger_add = mocker.patch.object(logger, "add")

        Main()

        assert logger_add.call_args_list[0].kwargs["level"] == "DEBUG"

    def test_init_hides_logger_source_location_by_default(self, mocker) -> None:
        mocker.patch("main.load_dotenv")
        mocker.patch.dict(os.environ, {}, clear=True)
        logger_add = mocker.patch.object(logger, "add")

        Main()

        logger_format = logger_add.call_args_list[0].kwargs["format"]
        logger_name_format = "<cyan>{name}</cyan>"
        source_location_format = "<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        assert logger_name_format not in logger_format
        assert source_location_format not in logger_format

    def test_init_shows_logger_name_and_source_location_when_log_level_is_debug(
        self, mocker
    ) -> None:
        mocker.patch.dict(os.environ, {"LOG_LEVEL": "debug"})
        logger_add = mocker.patch.object(logger, "add")

        Main()

        logger_format = logger_add.call_args_list[0].kwargs["format"]
        logger_name_format = "<cyan>{name}</cyan>"
        source_location_format = "<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        assert f"{logger_name_format}:{source_location_format}" in logger_format

    def test_init_loads_local_dotenv_file(self, mocker) -> None:
        logger_add = mocker.patch.object(logger, "add")
        load_dotenv = mocker.patch("main.load_dotenv")

        Main()

        load_dotenv.assert_called_once()
        assert load_dotenv.call_args.args == (".env.local",)
        assert logger_add.called

    def test_sonarr_log_to_file_configures_instance_sink(
        self, config, log_dir, log_retention, log_rotation, log_level, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        main = Main()
        logger_add = mocker.patch.object(logger, "add")

        main.start()

        file_sink_call = next(
            call
            for call in logger_add.call_args_list
            if call.args and call.args[0] == "/tmp/renamarr-logs/sonarr/sonarr.log"
        )
        assert file_sink_call.kwargs["format"]
        assert file_sink_call.kwargs["level"] == "DEBUG"
        assert file_sink_call.kwargs["rotation"] == "12:00"
        assert file_sink_call.kwargs["retention"] == "14 days"

        filter_fn = file_sink_call.kwargs["filter"]
        assert filter_fn({"extra": {"service": "sonarr", "instance": "sonarr"}})
        assert not filter_fn({"extra": {"service": "radarr", "instance": "sonarr"}})
        assert not filter_fn({"extra": {"service": "sonarr", "instance": "sonarr1"}})
        assert not filter_fn({"extra": {}})

    def test_sonarr_log_to_file_does_not_configure_sink_when_renamarr_disabled(
        self, config, log_dir, log_retention, log_rotation, log_level, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = False
        config.sonarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        main = Main()
        logger_add = mocker.patch.object(logger, "add")

        main.start()

        assert all(
            not (call.args and call.args[0] == "/tmp/renamarr-logs/sonarr/sonarr.log")
            for call in logger_add.call_args_list
        )

    def test_sonarr_log_to_file_warns_when_sink_setup_fails(
        self, log_dir, mock_loguru_warning, mocker
    ) -> None:
        main = Main()
        logger_add = mocker.patch.object(logger, "add")
        logger_add.side_effect = PermissionError("read-only file system")
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )

        configured = main._Main__configure_file_logging("sonarr", "sonarr")

        assert not configured
        contextualize.assert_called_once_with(service="sonarr", instance="sonarr")
        mock_loguru_warning.assert_any_call(
            "Unable to write logs to '/tmp/renamarr-logs/sonarr/sonarr.log'; continuing with stdout logging only."
        )
        assert isinstance(
            mock_loguru_warning.call_args_list[-1].args[0], PermissionError
        )

    def test_sonarr_series_scanner_hourly_job(
        self, config, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.spy(Job, "do")
        run_pending = mocker.spy(Scheduler, "run_pending")

        sonarr_series_scanner = mocker.patch("main.SonarrSeriesScanner")

        Main().start()

        sonarr_series_scanner.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            hours_before_air=config.sonarr[0].series_scanner.hours_before_air,
        )
        sonarr_series_scanner.return_value.scan.assert_called_once_with()
        job.assert_called()
        run_pending.assert_called_once()

    def test_sonarr_series_scanner_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        sonarr_series_scanner = mocker.patch("main.SonarrSeriesScanner")
        sonarr_series_scanner.return_value.scan.side_effect = exception
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )

        Main().start()

        sonarr_series_scanner.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            hours_before_air=config.sonarr[0].series_scanner.hours_before_air,
        )
        contextualize.assert_any_call(service="sonarr", instance=config.sonarr[0].name)
        mock_loguru_error.assert_called_once_with(exception)

    def test_sonarr_renamarr_scan(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.analyze_files = True
        config.sonarr[0].renamarr.rename_folders = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")

        Main().start()

        sonarr_renamarr.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            analyze_files=True,
            rename_folders=True,
        )
        sonarr_renamarr.return_value.scan.assert_called_once_with()

    def test_sonarr_renamarr_hourly_job(self, config, enable_scheduler, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")
        run_pending = mocker.spy(Scheduler, "run_pending")

        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")

        Main().start()

        sonarr_renamarr.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            analyze_files=config.sonarr[0].renamarr.analyze_files,
            rename_folders=config.sonarr[0].renamarr.rename_folders,
        )
        sonarr_renamarr.return_value.scan.assert_called_once_with()
        job.assert_called()
        run_pending.assert_called_once()

    def test_sonarr_renamarr_hourly_job_external_cron(
        self, config, external_cron, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.spy(Job, "do")

        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")

        Main().start()

        sonarr_renamarr.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            analyze_files=config.sonarr[0].renamarr.analyze_files,
            rename_folders=config.sonarr[0].renamarr.rename_folders,
        )
        sonarr_renamarr.return_value.scan.assert_called_once_with()
        job.assert_not_called()

    def test_sonarr_series_scanner_hourly_job_external_cron(
        self, config, external_cron, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.spy(Job, "do")

        series_scanner = mocker.patch("main.SonarrSeriesScanner")

        Main().start()

        series_scanner.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            hours_before_air=config.sonarr[0].series_scanner.hours_before_air,
        )
        series_scanner.return_value.scan.assert_called_once_with()
        job.assert_not_called()

    def test_sonarr_renamarr_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")
        sonarr_renamarr.return_value.scan.side_effect = exception
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )

        Main().start()

        sonarr_renamarr.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            analyze_files=config.sonarr[0].renamarr.analyze_files,
            rename_folders=config.sonarr[0].renamarr.rename_folders,
        )
        contextualize.assert_any_call(service="sonarr", instance=config.sonarr[0].name)
        mock_loguru_error.assert_called_once_with(exception)

    def test_config_parser_error(self, mock_loguru_error, capsys, mocker) -> None:
        exception = ConfigError("BOOM!")
        mocker.patch("pyconfigparser.configparser.get_config").side_effect = exception

        with pytest.raises(SystemExit) as excinfo:
            Main().start()

        mock_loguru_error.assert_called_with(exception)
        assert excinfo.value.code == 1

        mock_loguru_error.assert_any_call(
            "Unable to parse config file, Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
        )

    def test_config_file_not_found_error(
        self, mock_loguru_error, capsys, mocker
    ) -> None:
        exception = ConfigFileNotFoundError("BOOM!")
        mocker.patch("pyconfigparser.configparser.get_config").side_effect = exception

        with pytest.raises(SystemExit) as excinfo:
            Main().start()

        mock_loguru_error.assert_called_with(exception)
        assert excinfo.value.code == 1

        mock_loguru_error.assert_any_call(
            "Unable to locate config file, please check volume mount paths or set $CONFIG_DIR. The default config directory is /config/."
        )

    def test_config_dir_not_found_error(
        self, tmp_path, mock_loguru_error, mocker
    ) -> None:
        missing_config_dir = tmp_path / "missing-config-dir"
        os.environ["CONFIG_DIR"] = str(missing_config_dir)
        get_config = mocker.patch("pyconfigparser.configparser.get_config")

        try:
            with pytest.raises(SystemExit) as excinfo:
                Main().start()
        finally:
            del os.environ["CONFIG_DIR"]

        get_config.assert_not_called()
        mock_loguru_error.assert_any_call(
            f"Unable to access config directory {str(missing_config_dir)!r}; please check volume mount paths or set $CONFIG_DIR."
        )
        assert isinstance(mock_loguru_error.call_args_list[-1].args[0], OSError)
        assert excinfo.value.code == 1

    def test_radarr_renamarr_scan(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        radarr_renamarr = mocker.patch("main.RadarrRenamarr")

        Main().start()

        radarr_renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
            analyze_files=config.radarr[0].renamarr.analyze_files,
            rename_folders=config.radarr[0].renamarr.rename_folders,
        )
        radarr_renamarr.return_value.scan.assert_called_once_with()

    def test_radarr_renamarr_rename_folders_defaults_false(self, config) -> None:
        assert config.radarr[0].renamarr.rename_folders is False

    def test_radarr_renamarr_passes_rename_folders(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.analyze_files = True
        config.radarr[0].renamarr.rename_folders = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        radarr_renamarr = mocker.patch("main.RadarrRenamarr")

        Main().start()

        radarr_renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
            analyze_files=True,
            rename_folders=True,
        )
        radarr_renamarr.return_value.scan.assert_called_once_with()

    def test_radarr_log_to_file_configures_instance_sink(
        self, config, log_dir, log_retention, log_rotation, log_level, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        main = Main()
        logger_add = mocker.patch.object(logger, "add")

        main.start()

        file_sink_call = next(
            call
            for call in logger_add.call_args_list
            if call.args and call.args[0] == "/tmp/renamarr-logs/radarr/radarr.log"
        )
        assert file_sink_call.kwargs["format"]
        assert file_sink_call.kwargs["level"] == "DEBUG"
        assert file_sink_call.kwargs["rotation"] == "12:00"
        assert file_sink_call.kwargs["retention"] == "14 days"

        filter_fn = file_sink_call.kwargs["filter"]
        assert filter_fn({"extra": {"service": "radarr", "instance": "radarr"}})
        assert not filter_fn({"extra": {"service": "sonarr", "instance": "radarr"}})
        assert not filter_fn({"extra": {"service": "radarr", "instance": "radarr1"}})
        assert not filter_fn({"extra": {}})

    def test_radarr_log_to_file_warns_when_sink_setup_fails(
        self, log_dir, mock_loguru_warning, mocker
    ) -> None:
        main = Main()
        logger_add = mocker.patch.object(logger, "add")
        logger_add.side_effect = PermissionError("read-only file system")
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )

        configured = main._Main__configure_file_logging("radarr", "radarr")

        assert not configured
        contextualize.assert_called_once_with(service="radarr", instance="radarr")
        mock_loguru_warning.assert_any_call(
            "Unable to write logs to '/tmp/renamarr-logs/radarr/radarr.log'; continuing with stdout logging only."
        )
        assert isinstance(
            mock_loguru_warning.call_args_list[-1].args[0], PermissionError
        )

    def test_radarr_renamarr_hourly_job(self, config, enable_scheduler, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.spy(Job, "do")
        run_pending = mocker.spy(Scheduler, "run_pending")

        radarr_renamarr = mocker.patch("main.RadarrRenamarr")

        Main().start()

        radarr_renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
            analyze_files=config.radarr[0].renamarr.analyze_files,
            rename_folders=config.radarr[0].renamarr.rename_folders,
        )
        radarr_renamarr.return_value.scan.assert_called_once_with()
        job.assert_called()
        run_pending.assert_called_once()

    def test_radarr_renamarr_hourly_job_external_cron(
        self, config, external_cron, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        radarr_renamarr = mocker.patch("main.RadarrRenamarr")

        Main().start()

        radarr_renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
            analyze_files=config.radarr[0].renamarr.analyze_files,
            rename_folders=config.radarr[0].renamarr.rename_folders,
        )
        radarr_renamarr.return_value.scan.assert_called_once_with()
        job.assert_not_called()

    def test_radarr_renamarr_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        renamarr = mocker.patch("main.RadarrRenamarr")
        renamarr.return_value.scan.side_effect = exception
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )

        Main().start()

        renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
            analyze_files=config.radarr[0].renamarr.analyze_files,
            rename_folders=config.radarr[0].renamarr.rename_folders,
        )
        contextualize.assert_any_call(service="radarr", instance=config.radarr[0].name)
        mock_loguru_error.assert_called_once_with(exception)

    def test_sonarr_renamarr_custom_schedule(self, config, enable_scheduler, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = False
        config.sonarr[0].renamarr.schedule = "PT10M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job_spy = mocker.spy(Job, "do")
        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")

        Main().start()

        sonarr_renamarr.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            analyze_files=config.sonarr[0].renamarr.analyze_files,
            rename_folders=config.sonarr[0].renamarr.rename_folders,
        )
        sonarr_renamarr.return_value.scan.assert_called_once_with()
        job_spy.assert_called()

    def test_series_scanner_hourly_job_warns_when_schedule_set(
        self, config, mock_loguru_warning, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = True
        config.sonarr[0].series_scanner.schedule = "PT10M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch("main.SonarrSeriesScanner")

        Main().start()

        mock_loguru_warning.assert_any_call(
            "hourly_job is enabled; ignoring schedule field"
        )

    def test_radarr_hourly_job_warns_when_schedule_set(
        self, config, mock_loguru_warning, enable_scheduler, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.hourly_job = True
        config.radarr[0].renamarr.schedule = "PT10M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch("main.RadarrRenamarr")

        Main().start()

        mock_loguru_warning.assert_any_call(
            "hourly_job is enabled; ignoring schedule field"
        )

    def test_sonarr_series_scanner_custom_schedule(
        self, config, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = False
        config.sonarr[0].series_scanner.schedule = "PT30M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job_spy = mocker.spy(Job, "do")
        sonarr_series_scanner = mocker.patch("main.SonarrSeriesScanner")

        Main().start()

        sonarr_series_scanner.assert_called_once_with(
            name=config.sonarr[0].name,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
            hours_before_air=config.sonarr[0].series_scanner.hours_before_air,
        )
        sonarr_series_scanner.return_value.scan.assert_called_once_with()
        job_spy.assert_called()

    def test_radarr_renamarr_custom_schedule(
        self, config, enable_scheduler, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.hourly_job = False
        config.radarr[0].renamarr.schedule = "PT1H"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job_spy = mocker.spy(Job, "do")
        radarr_renamarr = mocker.patch("main.RadarrRenamarr")

        Main().start()

        radarr_renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
            analyze_files=config.radarr[0].renamarr.analyze_files,
            rename_folders=config.radarr[0].renamarr.rename_folders,
        )
        radarr_renamarr.return_value.scan.assert_called_once_with()
        job_spy.assert_called()

    def test_custom_schedule_external_cron(
        self, config, external_cron, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = False
        config.sonarr[0].renamarr.schedule = "PT10M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")
        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")

        Main().start()

        sonarr_renamarr.assert_called_once()
        sonarr_renamarr.return_value.scan.assert_called_once_with()
        job.assert_not_called()

    def test_hourly_job_warns_when_schedule_also_set(
        self, config, mock_loguru_warning, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = True
        config.sonarr[0].renamarr.schedule = "PT10M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch("main.SonarrRenamarr")

        Main().start()

        mock_loguru_warning.assert_any_call(
            "hourly_job is enabled; ignoring schedule field"
        )

    def test_register_custom_schedule_logs_info(
        self, config, mock_loguru_info, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = False
        config.sonarr[0].renamarr.schedule = "PT1H"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch("main.SonarrRenamarr")

        Main().start()

        mock_loguru_info.assert_any_call(
            "Registered custom schedule: PT1H (every 60 minutes)"
        )

    def test_register_custom_schedule_rounds_short_duration(
        self, config, mock_loguru_info, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = False
        config.sonarr[0].renamarr.schedule = "PT1M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch("main.SonarrRenamarr")

        Main().start()

        mock_loguru_info.assert_any_call(
            "Registered custom schedule: PT1M (every 1 minutes)"
        )

    def test_hourly_job_still_schedules_when_schedule_set(
        self, config, enable_scheduler, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = True
        config.sonarr[0].renamarr.schedule = "PT10M"
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job_spy = mocker.spy(Job, "do")
        sonarr_renamarr = mocker.patch("main.SonarrRenamarr")

        Main().start()

        sonarr_renamarr.return_value.scan.assert_called_once_with()
        job_spy.assert_called()
