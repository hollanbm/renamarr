import os
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path

import pytest
from loguru import logger
from pyconfigparser import Config, ConfigError, ConfigFileNotFoundError, configparser
from pytest_mock import MockerFixture
from schedule import Job, clear, get_jobs

from config_schema import CONFIG_SCHEMA
from main import Main
from renamarr.adapter_factory import ArrService
from renamarr.healthcheck.health_reporter import HealthReporter
from renamarr.logging_config import LoggingConfigurator
from renamarr.models.command import CommandPollingSettings

# disable config caching
configparser.hold_an_instance = False


class TestMain:
    @pytest.fixture(autouse=True)
    def clear_scheduled_jobs(self) -> Iterator[None]:
        clear()
        yield
        clear()

    @pytest.fixture(autouse=True)
    def mock_health_reporter(self, mocker: MockerFixture) -> None:
        self.health_reporter = mocker.Mock(spec=HealthReporter)
        self.running_job_context = mocker.MagicMock()
        self.health_reporter.running_job.return_value = self.running_job_context
        mocker.patch("main.HealthReporter", return_value=self.health_reporter)

    @pytest.fixture(autouse=True)
    def mock_logging_configurator(self, mocker: MockerFixture) -> None:
        self.logging_configurator = mocker.Mock(spec=LoggingConfigurator)
        self.logging_configurator_factory = mocker.patch(
            "main.LoggingConfigurator", return_value=self.logging_configurator
        )

    @pytest.fixture
    def config_dir(self, mocker: MockerFixture) -> None:
        mocker.patch.dict(os.environ, {"CONFIG_DIR": "tests/fixtures"})

    @pytest.fixture
    def config(self, mocker: MockerFixture) -> Config:
        self.scheduler_loop = mocker.patch.object(Main, "_run_scheduler_forever")
        return configparser.get_config(
            CONFIG_SCHEMA,
            config_dir="tests/fixtures",
            file_name="disabled.yml",
        )

    def test_all_disabled(self, config, mocker) -> None:
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config

        renamarr = mocker.patch("main.Renamarr")
        create_arr_adapter = mocker.patch("main.create_arr_adapter")
        job = mocker.patch.object(Job, "do")

        Main().start()

        renamarr.assert_not_called()
        create_arr_adapter.assert_not_called()
        job.assert_not_called()

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

    def test_start_supports_absolute_config_dir(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        config_directory = tmp_path / "config"
        config_directory.mkdir()
        config_path = config_directory / "config.yml"
        config_path.write_text(
            """sonarr:
  - name: absolute-sonarr
    url: https://absolute-sonarr.tld
    api_key: absolute-api-key
    renamarr:
      enabled: true
      analyze_files: true
      rename_folders: true
      schedule:
        enabled: false
""",
            encoding="utf-8",
        )
        original_directory = Path.cwd()
        mocker.patch.dict(os.environ, {"CONFIG_DIR": str(tmp_path)})
        adapter = mocker.sentinel.absolute_sonarr_adapter
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", return_value=adapter
        )
        renamarr = mocker.patch("main.Renamarr")

        observed_directory = original_directory
        try:
            Main().start()
            observed_directory = Path.cwd()
        finally:
            os.chdir(original_directory)

        assert observed_directory == original_directory
        create_arr_adapter.assert_called_once_with(
            service=ArrService.SONARR,
            url="https://absolute-sonarr.tld",
            api_key="absolute-api-key",
        )
        renamarr.assert_called_once_with(
            name="absolute-sonarr",
            adapter=adapter,
            analyze_files=True,
            rename_folders=True,
            command_polling=CommandPollingSettings(),
        )
        renamarr.return_value.scan.assert_called_once_with()

    def test_init_loads_dotenv_before_configuring_logging(
        self, mocker: MockerFixture
    ) -> None:
        load_dotenv = mocker.patch("main.load_dotenv")
        initialization = mocker.Mock()
        initialization.attach_mock(load_dotenv, "load_dotenv")
        initialization.attach_mock(
            self.logging_configurator_factory, "logging_configurator"
        )

        Main()

        assert initialization.mock_calls == [
            mocker.call.load_dotenv(".env.local"),
            mocker.call.logging_configurator(),
        ]
        self.logging_configurator.configure_stdout.assert_called_once_with()

    def test_scheduler_loop_runs_pending_and_updates_health(
        self, mocker: MockerFixture
    ) -> None:
        run_pending = mocker.patch("main.schedule.run_pending")
        stop_scheduler = RuntimeError("stop scheduler")
        sleep = mocker.patch("main.sleep", side_effect=[None, stop_scheduler])

        with pytest.raises(RuntimeError, match="stop scheduler"):
            Main()._run_scheduler_forever()

        self.health_reporter.idle.assert_called_once_with()
        assert self.health_reporter.heartbeat.call_count == 2
        assert run_pending.call_count == 2
        assert sleep.call_args_list == [mocker.call(1), mocker.call(1)]

    @pytest.mark.parametrize("service", [ArrService.SONARR, ArrService.RADARR])
    def test_log_to_file_configures_instance_sink(
        self, config: Config, service: ArrService, mocker: MockerFixture
    ) -> None:
        instance_config = getattr(config, service.value)[0]
        instance_config.renamarr.enabled = True
        instance_config.renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        mocker.patch("main.create_arr_adapter")
        renamarr = mocker.patch("main.Renamarr")
        events: list[str] = []
        self.logging_configurator.configure_instance_file.side_effect = lambda *_: (
            events.append("configure")
        )
        renamarr.return_value.scan.side_effect = lambda: events.append("scan")

        Main().start()

        self.logging_configurator.configure_instance_file.assert_called_once_with(
            service.value, instance_config.name
        )
        assert events == ["configure", "scan"]

    def test_log_to_file_does_not_configure_sink_when_renamarr_disabled(
        self, config, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = False
        config.sonarr[0].renamarr.log_to_file = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        Main().start()

        self.logging_configurator.configure_instance_file.assert_not_called()

    def test_sonarr_renamarr_scan(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.analyze_files = True
        config.sonarr[0].renamarr.rename_folders = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        adapter = mocker.sentinel.sonarr_adapter
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", return_value=adapter
        )
        renamarr = mocker.patch("main.Renamarr")

        Main().start()

        create_arr_adapter.assert_called_once_with(
            service=ArrService.SONARR,
            url=config.sonarr[0].url,
            api_key=config.sonarr[0].api_key,
        )
        renamarr.assert_called_once_with(
            name=config.sonarr[0].name,
            adapter=adapter,
            analyze_files=True,
            rename_folders=True,
            command_polling=config.sonarr[0].renamarr.command_polling,
        )
        renamarr.return_value.scan.assert_called_once_with()
        self.health_reporter.running_job.assert_called_once_with()

    @pytest.mark.parametrize("failure_source", ["adapter_creation", "scan"])
    def test_unexpected_renamarr_job_failure_is_logged_and_contained(
        self,
        config,
        failure_source: str,
        mock_loguru_warning,
        mocker,
    ) -> None:
        service_config = config.sonarr[0]
        service_config.renamarr.enabled = True
        service_config.renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config", return_value=config)
        error = RuntimeError(f"{failure_source} failed")
        create_arr_adapter = mocker.patch("main.create_arr_adapter")
        renamarr = mocker.patch("main.Renamarr")
        if failure_source == "adapter_creation":
            create_arr_adapter.side_effect = error
        else:
            renamarr.return_value.scan.side_effect = error
        log_exception = mocker.patch.object(logger, "exception")
        contextualize = mocker.patch.object(
            logger, "contextualize", return_value=nullcontext()
        )
        every = mocker.patch("main.schedule.every")

        Main().start()

        contextualize.assert_any_call(
            service=ArrService.SONARR.value,
            instance=service_config.name,
        )
        log_exception.assert_called_once_with(
            "Unexpected failure while running Renamarr for sonarr instance "
            f"{service_config.name!r}."
        )
        deprecation_warnings = [
            call
            for call in mock_loguru_warning.call_args_list
            if "renamarr.hourly_job is deprecated" in call.args[0]
        ]
        assert len(deprecation_warnings) == 2
        every.assert_called_once_with(
            service_config.renamarr.schedule.interval.total_minutes
        )
        every.return_value.minutes.do.assert_called_once_with(
            mocker.ANY,
            service=ArrService.SONARR,
            config=service_config,
        )

    @pytest.mark.parametrize("service", ["sonarr", "radarr"])
    def test_default_renamarr_schedule_runs_immediately_and_hourly(
        self, config: Config, service: str, mocker: MockerFixture
    ) -> None:
        service_config = getattr(config, service)[0]
        arr_service = ArrService(service)
        service_config.renamarr.enabled = True
        assert service_config.renamarr.schedule.enabled is True
        assert service_config.renamarr.schedule.interval.total_minutes == 60
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        adapter = mocker.sentinel.scheduled_adapter
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", return_value=adapter
        )
        renamarr = mocker.patch("main.Renamarr")

        Main().start()

        renamarr.return_value.scan.assert_called_once_with()
        jobs = get_jobs()
        assert len(jobs) == 1
        assert jobs[0].interval == 60
        assert jobs[0].unit == "minutes"
        self.scheduler_loop.assert_called_once_with()

        jobs[0].run()

        expected_adapter_call = mocker.call(
            service=arr_service,
            url=service_config.url,
            api_key=service_config.api_key,
        )
        assert create_arr_adapter.call_args_list == [
            expected_adapter_call,
            expected_adapter_call,
        ]
        expected_renamarr_call = mocker.call(
            name=service_config.name,
            adapter=adapter,
            analyze_files=service_config.renamarr.analyze_files,
            rename_folders=service_config.renamarr.rename_folders,
            command_polling=service_config.renamarr.command_polling,
        )
        assert renamarr.call_args_list == [
            expected_renamarr_call,
            expected_renamarr_call,
        ]
        assert renamarr.return_value.scan.call_count == 2
        assert self.health_reporter.running_job.call_args_list == [
            mocker.call(),
            mocker.call(),
        ]
        assert self.running_job_context.__enter__.call_args_list == [
            mocker.call(),
            mocker.call(),
        ]
        assert self.running_job_context.__exit__.call_args_list == [
            mocker.call(None, None, None),
            mocker.call(None, None, None),
        ]

    def test_start_runs_every_enabled_instance(
        self, config: Config, mocker: MockerFixture
    ) -> None:
        enabled_instances = [
            (ArrService.SONARR, config.sonarr[0]),
            (ArrService.SONARR, config.sonarr[1]),
            (ArrService.RADARR, config.radarr[0]),
            (ArrService.RADARR, config.radarr[1]),
        ]
        for _, instance_config in enabled_instances:
            instance_config.renamarr.enabled = True
            instance_config.renamarr.schedule.enabled = False
        mocker.patch("pyconfigparser.configparser.get_config", return_value=config)
        adapters = [mocker.Mock() for _ in enabled_instances]
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", side_effect=adapters
        )
        jobs = [mocker.Mock() for _ in enabled_instances]
        renamarr = mocker.patch("main.Renamarr", side_effect=jobs)

        Main().start()

        assert create_arr_adapter.call_args_list == [
            mocker.call(
                service=service,
                url=instance_config.url,
                api_key=instance_config.api_key,
            )
            for service, instance_config in enabled_instances
        ]
        assert renamarr.call_args_list == [
            mocker.call(
                name=instance_config.name,
                adapter=adapter,
                analyze_files=instance_config.renamarr.analyze_files,
                rename_folders=instance_config.renamarr.rename_folders,
                command_polling=instance_config.renamarr.command_polling,
            )
            for (_, instance_config), adapter in zip(
                enabled_instances, adapters, strict=True
            )
        ]
        for job in jobs:
            job.scan.assert_called_once_with()
        self.scheduler_loop.assert_not_called()

    def test_external_cron_does_not_disable_explicit_renamarr_schedule(
        self, config: Config, mocker: MockerFixture
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.schedule.enabled = True
        mocker.patch.dict(os.environ, {"EXTERNAL_CRON": "TRUE"})
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        renamarr = mocker.patch("main.Renamarr")
        mocker.patch("main.create_arr_adapter")

        Main().start()

        renamarr.return_value.scan.assert_called_once_with()
        jobs = get_jobs()
        assert len(jobs) == 1
        assert jobs[0].interval == 60
        assert jobs[0].unit == "minutes"
        self.scheduler_loop.assert_called_once_with()

    @pytest.mark.parametrize("service", ["sonarr", "radarr"])
    def test_deprecated_hourly_job_warns_before_and_after_renamarr_job(
        self, config, service: str, mock_loguru_warning, mocker
    ) -> None:
        service_config = getattr(config, service)[0]
        service_config.renamarr.enabled = True
        service_config.renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        mocker.patch("main.create_arr_adapter")
        renamarr = mocker.patch("main.Renamarr")
        warning_message = (
            "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled "
            "instead. Remove renamarr.hourly_job after migrating the schedule "
            "configuration."
        )
        events: list[str] = []

        def record_warning(message: object) -> None:
            if message == warning_message:
                events.append("warning")

        mock_loguru_warning.side_effect = record_warning
        renamarr.return_value.scan.side_effect = lambda: events.append("scan")

        Main().start()

        renamarr.return_value.scan.assert_called_once_with()
        assert events == ["warning", "scan", "warning"]
        deprecation_warnings = [
            call
            for call in mock_loguru_warning.call_args_list
            if "renamarr.hourly_job is deprecated" in call.args[0]
        ]
        assert deprecation_warnings == [
            mocker.call(warning_message),
            mocker.call(warning_message),
        ]

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

        adapter = mocker.sentinel.radarr_adapter
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", return_value=adapter
        )
        renamarr = mocker.patch("main.Renamarr")

        Main().start()

        create_arr_adapter.assert_called_once_with(
            service=ArrService.RADARR,
            url=config.radarr[0].url,
            api_key=config.radarr[0].api_key,
        )
        renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            adapter=adapter,
            analyze_files=config.radarr[0].renamarr.analyze_files,
            rename_folders=config.radarr[0].renamarr.rename_folders,
            command_polling=config.radarr[0].renamarr.command_polling,
        )
        renamarr.return_value.scan.assert_called_once_with()
        self.health_reporter.running_job.assert_called_once_with()

    def test_radarr_renamarr_rename_folders_defaults_false(self, config) -> None:
        assert config.radarr[0].renamarr.rename_folders is False

    def test_radarr_renamarr_passes_rename_folders(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.analyze_files = True
        config.radarr[0].renamarr.rename_folders = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        adapter = mocker.sentinel.radarr_adapter
        mocker.patch("main.create_arr_adapter", return_value=adapter)
        renamarr = mocker.patch("main.Renamarr")

        Main().start()

        renamarr.assert_called_once_with(
            name=config.radarr[0].name,
            adapter=adapter,
            analyze_files=True,
            rename_folders=True,
            command_polling=config.radarr[0].renamarr.command_polling,
        )
        renamarr.return_value.scan.assert_called_once_with()

    @pytest.mark.parametrize("service", ["sonarr", "radarr"])
    def test_disabled_renamarr_schedule_runs_once(
        self, config, service, mocker
    ) -> None:
        service_config = getattr(config, service)[0]
        service_config.renamarr.enabled = True
        service_config.renamarr.schedule.enabled = False
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch("main.create_arr_adapter")
        renamarr = mocker.patch("main.Renamarr")

        Main().start()

        renamarr.return_value.scan.assert_called_once_with()
        assert get_jobs() == []
        self.scheduler_loop.assert_not_called()
        self.health_reporter.idle.assert_not_called()

    def test_renamarr_schedule_uses_total_minutes(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.schedule.enabled = True
        config.radarr[0].renamarr.schedule.interval = mocker.Mock(total_minutes=1504)
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        every = mocker.patch("main.schedule.every")
        mocker.patch("main.create_arr_adapter")
        renamarr = mocker.patch("main.Renamarr")

        Main().start()

        every.assert_called_once_with(1504)
        every.return_value.minutes.do.assert_called_once_with(
            mocker.ANY, service=ArrService.RADARR, config=config.radarr[0]
        )
        renamarr.return_value.scan.assert_called_once_with()
