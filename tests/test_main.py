import logging
import os
import select
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from typing import Protocol

import pytest
from pyconfigparser import Config, ConfigError, ConfigFileNotFoundError, configparser
from pytest_mock import MockerFixture
from schedule import Job, clear, get_jobs
from structlog.contextvars import bound_contextvars, get_contextvars

from config_schema import CONFIG_SCHEMA
from main import Main
from renamarr.adapter_factory import ArrService
from renamarr.healthcheck.health_reporter import HealthReporter
from renamarr.logging_config import LoggingConfigurator
from renamarr.models.command import CommandPollingSettings
from renamarr.protocols import ArrAdapter

# disable config caching
configparser.hold_an_instance = False


class _IntervalConfig(Protocol):
    total_minutes: int


class _ScheduleConfig(Protocol):
    enabled: bool
    interval: _IntervalConfig


class _RenamarrConfig(Protocol):
    enabled: bool
    hourly_job: bool
    analyze_files: bool
    rename_folders: bool
    schedule: _ScheduleConfig
    command_polling: CommandPollingSettings


class _ServiceConfig(Protocol):
    name: str
    url: str
    api_key: str
    renamarr: _RenamarrConfig


def _service_config(
    config: Config, service: str, instance_index: int = 0
) -> _ServiceConfig:
    return getattr(config, service)[instance_index]


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
        adapter = mocker.Mock(spec=ArrAdapter)
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
        adapter.close.assert_called_once_with()

    def test_init_loads_dotenv_before_creating_logging_configurator(
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
        self.logging_configurator.configure_stdout.assert_not_called()
        self.logging_configurator.configure_otlp.assert_not_called()

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

    def test_start_configures_logging_before_application_and_shuts_down(
        self, mocker: MockerFixture
    ) -> None:
        application = Main()
        run_application = mocker.patch.object(application, "_start")
        lifecycle = mocker.Mock()
        lifecycle.attach_mock(self.logging_configurator, "logging")
        lifecycle.attach_mock(run_application, "application")
        previous_handlers = {
            signum: signal.getsignal(signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        }

        application.start()

        assert lifecycle.mock_calls == [
            mocker.call.logging.configure_stdout(),
            mocker.call.logging.configure_otlp(),
            mocker.call.application(),
            mocker.call.logging.shutdown(),
        ]
        for signum, handler in previous_handlers.items():
            assert signal.getsignal(signum) == handler

    @pytest.mark.parametrize(
        "failure_point", ["configure_stdout", "configure_otlp", "_start"]
    )
    def test_start_shuts_down_after_partial_setup_or_application_error(
        self, failure_point: str, mocker: MockerFixture
    ) -> None:
        application = Main()
        run_application = mocker.patch.object(application, "_start")
        error = RuntimeError("lifecycle failure")
        if failure_point == "_start":
            run_application.side_effect = error
        else:
            getattr(self.logging_configurator, failure_point).side_effect = error

        with pytest.raises(RuntimeError, match="lifecycle failure") as excinfo:
            application.start()

        assert excinfo.value is error
        self.logging_configurator.shutdown.assert_called_once_with()

    def test_start_restores_handlers_after_shutdown_error(
        self, mocker: MockerFixture
    ) -> None:
        application = Main()
        mocker.patch.object(application, "_start")
        self.logging_configurator.shutdown.side_effect = RuntimeError("shutdown failed")
        previous_handlers = {
            signum: signal.getsignal(signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        }

        with pytest.raises(RuntimeError, match="shutdown failed"):
            application.start()

        for signum, handler in previous_handlers.items():
            assert signal.getsignal(signum) == handler

    @pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
    @pytest.mark.parametrize("shutdown_fails", [False, True])
    def test_signal_drains_logging_ignores_repeated_signals_and_preserves_exit_code(
        self,
        signum: signal.Signals,
        shutdown_fails: bool,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        application = Main()
        mocker.patch.object(
            application, "_start", side_effect=lambda: signal.raise_signal(signum)
        )
        previous_handlers = {
            handled_signal: signal.getsignal(handled_signal)
            for handled_signal in (signal.SIGINT, signal.SIGTERM)
        }

        def shutdown() -> None:
            for handled_signal in (signal.SIGINT, signal.SIGTERM):
                assert signal.getsignal(handled_signal) == signal.SIG_IGN
                signal.raise_signal(handled_signal)
            if shutdown_fails:
                raise RuntimeError("shutdown failed")

        self.logging_configurator.shutdown.side_effect = shutdown

        with pytest.raises(SystemExit) as excinfo:
            application.start()

        assert excinfo.value.code == 128 + signum
        self.logging_configurator.shutdown.assert_called_once_with()
        assert [record.message for record in caplog.records] == ["Shutdown requested"]
        assert caplog.records[0].__dict__["signal_number"] == signum
        for handled_signal, handler in previous_handlers.items():
            assert signal.getsignal(handled_signal) == handler

    def test_signal_registration_failure_closes_logging_and_restores_prior_handler(
        self, mocker: MockerFixture
    ) -> None:
        original_handler = signal.getsignal(signal.SIGINT)
        signal_handler = mocker.patch(
            "main.signal.signal",
            side_effect=[
                original_handler,
                ValueError("signal setup failed"),
                None,
                None,
            ],
        )
        application = Main()

        with pytest.raises(ValueError, match="signal setup failed"):
            application.start()

        assert signal_handler.call_args_list == [
            mocker.call(signal.SIGINT, application._request_termination),
            mocker.call(signal.SIGTERM, application._request_termination),
            mocker.call(signal.SIGINT, signal.SIG_IGN),
            mocker.call(signal.SIGINT, original_handler),
        ]
        self.logging_configurator.configure_stdout.assert_not_called()
        self.logging_configurator.shutdown.assert_called_once_with()

    def test_signal_still_closes_logging_when_shutdown_message_fails(
        self, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
    ) -> None:
        application = Main()
        mocker.patch.object(
            application,
            "_start",
            side_effect=lambda: signal.raise_signal(signal.SIGTERM),
        )
        broken_output = mocker.patch.object(
            caplog.handler, "emit", side_effect=RuntimeError("output failed")
        )

        with pytest.raises(SystemExit) as excinfo:
            application.start()

        assert excinfo.value.code == 128 + signal.SIGTERM
        broken_output.assert_called_once()
        self.logging_configurator.shutdown.assert_called_once_with()

    @pytest.mark.parametrize("cleanup_fails", [False, True])
    def test_signal_during_job_cannot_be_swallowed_by_adapter_cleanup(
        self,
        config: Config,
        cleanup_fails: bool,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        instance_config = _service_config(config, "sonarr")
        instance_config.renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config", return_value=config)
        adapter = mocker.Mock(spec=ArrAdapter)
        mocker.patch("main.create_arr_adapter", return_value=adapter)
        renamarr = mocker.patch("main.Renamarr")
        renamarr.return_value.scan.side_effect = lambda: signal.raise_signal(
            signal.SIGTERM
        )
        if cleanup_fails:
            adapter.close.side_effect = RuntimeError("cleanup failed")
        every = mocker.patch("main.schedule.every")

        with bound_contextvars(arr_type="outer"):
            with pytest.raises(SystemExit) as excinfo:
                Main().start()
            assert get_contextvars() == {"arr_type": "outer"}

        assert excinfo.value.code == 128 + signal.SIGTERM
        adapter.close.assert_called_once_with()
        self.logging_configurator.shutdown.assert_called_once_with()
        every.assert_not_called()
        assert caplog.records[-1].message == "Shutdown requested"
        assert "instance" not in caplog.records[-1].__dict__

    def test_process_sigterm_flushes_logs_and_exits_with_signal_status(
        self, tmp_path: Path
    ) -> None:
        script = dedent("""\
            import signal
            import sys
            from pathlib import Path
            import main

            class RecordingLoggingConfigurator(main.LoggingConfigurator):
                def shutdown(self):
                    super().shutdown()
                    Path(sys.argv[1]).write_text("closed", encoding="utf-8")

            class WaitingMain(main.Main):
                def _start(self):
                    print("ready", flush=True)
                    signal.pause()

            health_reporter = main.HealthReporter
            main.HealthReporter = lambda: health_reporter(path=Path(sys.argv[2]))
            main.LoggingConfigurator = RecordingLoggingConfigurator
            WaitingMain().start()
            """)
        shutdown_marker = tmp_path / "shutdown"
        environment = os.environ | {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "OTEL_LOGS_EXPORTER": "none",
            "LOG_FORMAT": "json",
            "LOG_LEVEL": "INFO",
        }

        with subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(shutdown_marker),
                str(tmp_path / "health"),
            ],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as process:
            try:
                assert process.stdout is not None
                assert select.select([process.stdout], [], [], 10)[0]
                assert process.stdout.readline().strip() == "ready"
                process.send_signal(signal.SIGTERM)
                output, _ = process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()

        assert process.returncode == 128 + signal.SIGTERM
        assert shutdown_marker.read_text(encoding="utf-8") == "closed"
        assert "Shutdown requested" in output

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

        adapter = mocker.Mock(spec=ArrAdapter)
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
        adapter.close.assert_called_once_with()
        self.health_reporter.running_job.assert_called_once_with()

    @pytest.mark.parametrize("failure_source", ["adapter_creation", "scan", "cleanup"])
    def test_unexpected_renamarr_job_failure_is_logged_and_contained(
        self,
        config: Config,
        failure_source: str,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        service_config = _service_config(config, "sonarr")
        service_config.renamarr.enabled = True
        service_config.renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config", return_value=config)
        error = RuntimeError(f"{failure_source} failed")
        adapter = mocker.Mock(spec=ArrAdapter)
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", return_value=adapter
        )
        renamarr = mocker.patch("main.Renamarr")
        if failure_source == "adapter_creation":
            create_arr_adapter.side_effect = error
        elif failure_source == "scan":
            renamarr.return_value.scan.side_effect = error
        else:
            adapter.close.side_effect = error
        every = mocker.patch("main.schedule.every")

        Main().start()

        errors = [
            record for record in caplog.records if record.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        record = errors[0]
        assert record.message == "Unexpected failure while running Renamarr."
        assert record.__dict__["arr_type"] == ArrService.SONARR.value
        assert record.__dict__["instance"] == service_config.name
        assert record.__dict__["phase"] == "job"
        assert record.exc_info is not None
        assert record.exc_info[1] is error
        assert get_contextvars() == {}
        expected_close_count = 0 if failure_source == "adapter_creation" else 1
        assert adapter.close.call_count == expected_close_count
        deprecation_warnings = [
            record
            for record in caplog.records
            if "renamarr.hourly_job is deprecated" in record.message
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
        adapter = mocker.Mock(spec=ArrAdapter)
        create_arr_adapter = mocker.patch(
            "main.create_arr_adapter", return_value=adapter
        )
        renamarr = mocker.patch("main.Renamarr")
        lifecycle = mocker.Mock()
        lifecycle.attach_mock(renamarr.return_value.scan, "scan")
        lifecycle.attach_mock(adapter.close, "close")

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
        assert lifecycle.mock_calls == [
            mocker.call.scan(),
            mocker.call.close(),
            mocker.call.scan(),
            mocker.call.close(),
        ]
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
            (ArrService.SONARR, _service_config(config, "sonarr")),
            (ArrService.SONARR, _service_config(config, "sonarr", 1)),
            (ArrService.RADARR, _service_config(config, "radarr")),
            (ArrService.RADARR, _service_config(config, "radarr", 1)),
        ]
        for _, instance_config in enabled_instances:
            instance_config.renamarr.enabled = True
            instance_config.renamarr.schedule.enabled = False
        mocker.patch("pyconfigparser.configparser.get_config", return_value=config)
        adapters = [mocker.Mock(spec=ArrAdapter) for _ in enabled_instances]
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
        for job, adapter in zip(jobs, adapters, strict=True):
            job.scan.assert_called_once_with()
            adapter.close.assert_called_once_with()
        self.scheduler_loop.assert_not_called()

    def test_external_cron_does_not_disable_explicit_renamarr_schedule(
        self, config: Config, mocker: MockerFixture
    ) -> None:
        service_config = _service_config(config, "radarr")
        service_config.renamarr.enabled = True
        service_config.renamarr.schedule.enabled = True
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
        self,
        config: Config,
        service: str,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
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
        messages_at_scan: list[str] = []
        renamarr.return_value.scan.side_effect = lambda: messages_at_scan.extend(
            record.message for record in caplog.records
        )

        Main().start()

        renamarr.return_value.scan.assert_called_once_with()
        assert messages_at_scan.count(warning_message) == 1
        deprecation_warnings = [
            record
            for record in caplog.records
            if "renamarr.hourly_job is deprecated" in record.message
        ]
        assert len(deprecation_warnings) == 2
        for record in deprecation_warnings:
            assert record.message == warning_message
            assert record.levelno == logging.WARNING
            assert record.__dict__["arr_type"] == service
            assert record.__dict__["instance"] == service_config.name

    @pytest.mark.parametrize(
        ("error_type", "expected_message"),
        [
            (
                ConfigError,
                "Unable to parse config file, Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example",
            ),
            (
                ConfigFileNotFoundError,
                "Unable to locate config file, please check volume mount paths or set $CONFIG_DIR. The default config directory is /config/.",
            ),
        ],
    )
    def test_configuration_error_is_logged_and_exits_after_logging_shutdown(
        self,
        error_type: type[ConfigError | ConfigFileNotFoundError],
        expected_message: str,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        exception = error_type("BOOM!")
        mocker.patch("pyconfigparser.configparser.get_config", side_effect=exception)

        with pytest.raises(SystemExit) as excinfo:
            Main().start()

        assert excinfo.value.code == 1
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.message == expected_message
        assert record.levelno == logging.ERROR
        assert record.__dict__["error"] == str(exception)
        assert record.__dict__["phase"] == "configuration"
        assert record.__dict__["config_dir"] == os.getenv("CONFIG_DIR", "/")
        self.logging_configurator.shutdown.assert_called_once_with()

    def test_config_dir_not_found_error(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        missing_config_dir = tmp_path / "missing-config-dir"
        mocker.patch.dict(os.environ, {"CONFIG_DIR": str(missing_config_dir)})
        get_config = mocker.patch("pyconfigparser.configparser.get_config")

        with pytest.raises(SystemExit) as excinfo:
            Main().start()

        get_config.assert_not_called()
        assert caplog.records[0].message == (
            "Unable to access config directory; please check volume mount paths or set $CONFIG_DIR."
        )
        assert caplog.records[0].__dict__["config_dir"] == str(missing_config_dir)
        assert str(missing_config_dir) in caplog.records[0].__dict__["error"]
        assert excinfo.value.code == 1

    def test_radarr_renamarr_scan(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        adapter = mocker.Mock(spec=ArrAdapter)
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
        adapter.close.assert_called_once_with()
        self.health_reporter.running_job.assert_called_once_with()

    def test_radarr_renamarr_rename_folders_defaults_false(self, config) -> None:
        assert config.radarr[0].renamarr.rename_folders is False

    def test_radarr_renamarr_passes_rename_folders(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.analyze_files = True
        config.radarr[0].renamarr.rename_folders = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")
        adapter = mocker.Mock(spec=ArrAdapter)
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
        adapter.close.assert_called_once_with()

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
