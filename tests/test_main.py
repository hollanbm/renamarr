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

from renamarr.observability import JobResult, ServiceName

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

    def test_init_loads_local_dotenv_file(self, mocker) -> None:
        load_dotenv = mocker.patch("main.load_dotenv")
        logging_configurator = mocker.patch("main.LoggingConfigurator").return_value

        Main()

        load_dotenv.assert_called_once_with(".env.local")
        logging_configurator.configure_stdout.assert_called_once_with()

    def test_sonarr_log_to_file_configures_instance_sink(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        logging_configurator = mocker.patch("main.LoggingConfigurator").return_value

        Main().start()

        logging_configurator.configure_instance_file.assert_called_once_with(
            ServiceName.SONARR, config.sonarr[0].name
        )

    def test_sonarr_log_to_file_does_not_configure_sink_when_renamarr_disabled(
        self, config, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = False
        config.sonarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        logging_configurator = mocker.patch("main.LoggingConfigurator").return_value

        Main().start()

        logging_configurator.configure_instance_file.assert_not_called()

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
        contextualize.assert_any_call(
            service=ServiceName.SONARR, instance=config.sonarr[0].name
        )
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

    def test_job_observability_records_success_and_flushes(
        self, config, fake_observability, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        mocker.patch("main.configure_observability", return_value=fake_observability)
        mocker.patch("main.time", return_value=100.0)
        mocker.patch("main.perf_counter", side_effect=[10.0, 12.5])
        mocker.patch("main.SonarrRenamarr")

        Main().start()

        fake_observability.start_span.assert_called_once_with(
            "renamarr.job.sonarr.renamarr",
            attributes={
                "service": ServiceName.SONARR,
                "name": config.sonarr[0].name,
                "job": "renamarr",
            },
        )
        fake_observability.record_job_started.assert_called_once_with(
            ServiceName.SONARR,
            config.sonarr[0].name,
            "renamarr",
            100.0,
        )
        fake_observability.record_job.assert_called_once_with(
            ServiceName.SONARR,
            config.sonarr[0].name,
            "renamarr",
            JobResult.SUCCESS,
            2.5,
        )
        fake_observability.force_flush.assert_called_once_with()
        fake_observability.shutdown.assert_called_once_with()

    def test_job_observability_records_failure_and_flushes(
        self, config, fake_observability, mock_loguru_error, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        mocker.patch("main.configure_observability", return_value=fake_observability)
        mocker.patch("main.time", return_value=101.0)
        mocker.patch("main.perf_counter", side_effect=[1.0, 4.0])
        exception = CliArrError("BOOM!")
        radarr_renamarr = mocker.patch("main.RadarrRenamarr")
        radarr_renamarr.return_value.scan.side_effect = exception

        Main().start()

        fake_observability.start_span.assert_called_once_with(
            "renamarr.job.radarr.renamarr",
            attributes={
                "service": ServiceName.RADARR,
                "name": config.radarr[0].name,
                "job": "renamarr",
            },
        )
        fake_observability.record_job_started.assert_called_once_with(
            ServiceName.RADARR,
            config.radarr[0].name,
            "renamarr",
            101.0,
        )
        fake_observability.record_job.assert_called_once_with(
            ServiceName.RADARR,
            config.radarr[0].name,
            "renamarr",
            JobResult.FAILED,
            3.0,
        )
        fake_observability.force_flush.assert_called_once_with()
        fake_observability.shutdown.assert_called_once_with()
        mock_loguru_error.assert_called_once_with(exception)

    def test_job_observability_records_unexpected_failure_before_reraising(
        self, config, fake_observability, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        mocker.patch("main.configure_observability", return_value=fake_observability)
        mocker.patch("main.time", return_value=101.0)
        mocker.patch("main.perf_counter", side_effect=[1.0, 4.0])
        exception = RuntimeError("BOOM!")
        radarr_renamarr = mocker.patch("main.RadarrRenamarr")
        radarr_renamarr.return_value.scan.side_effect = exception

        with pytest.raises(RuntimeError) as excinfo:
            Main().start()

        assert excinfo.value is exception
        fake_observability.record_job_started.assert_called_once_with(
            ServiceName.RADARR,
            config.radarr[0].name,
            "renamarr",
            101.0,
        )
        fake_observability.record_job.assert_called_once_with(
            ServiceName.RADARR,
            config.radarr[0].name,
            "renamarr",
            JobResult.FAILED,
            3.0,
        )
        fake_observability.force_flush.assert_called_once_with()
        fake_observability.shutdown.assert_called_once_with()

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
        contextualize.assert_any_call(
            service=ServiceName.SONARR, instance=config.sonarr[0].name
        )
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

    def test_radarr_log_to_file_configures_instance_sink(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        logging_configurator = mocker.patch("main.LoggingConfigurator").return_value

        Main().start()

        logging_configurator.configure_instance_file.assert_called_once_with(
            ServiceName.RADARR, config.radarr[0].name
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
        contextualize.assert_any_call(
            service=ServiceName.RADARR, instance=config.radarr[0].name
        )
        mock_loguru_error.assert_called_once_with(exception)
