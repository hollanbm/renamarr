import os
from collections.abc import Iterator
from contextlib import contextmanager
from sys import exit
from time import sleep
from typing import NoReturn, Protocol

import schedule
from dotenv import load_dotenv
from loguru import logger
from pyconfigparser import ConfigError, ConfigFileNotFoundError, configparser

from config_schema import CONFIG_SCHEMA
from interval import Interval
from renamarr.adapter_factory import ArrService, create_arr_adapter
from renamarr.healthcheck.health_reporter import HealthReporter
from renamarr.logging_config import LoggingConfigurator
from renamarr.models.command import CommandPollingSettings
from renamarr.renamarr import Renamarr

_DEPRECATED_HOURLY_JOB_WARNING: str = (
    "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. "
    "Remove renamarr.hourly_job after migrating the schedule configuration."
)


class _ScheduleConfig(Protocol):
    enabled: bool
    interval: Interval


class _RenamarrConfig(Protocol):
    enabled: bool
    analyze_files: bool
    rename_folders: bool
    log_to_file: bool
    schedule: _ScheduleConfig
    command_polling: CommandPollingSettings


class _ArrInstanceConfig(Protocol):
    name: str
    url: str
    api_key: str
    renamarr: _RenamarrConfig


class Main:
    """
    This class handles config parsing, and job scheduling
    """

    def __init__(self) -> None:
        load_dotenv(".env.local")
        self._health_reporter = HealthReporter()
        self._logging_configurator = LoggingConfigurator()
        self._logging_configurator.configure_stdout()

    def __renamarr_job(self, service: ArrService, config: _ArrInstanceConfig) -> None:
        with (
            self._health_reporter.running_job(),
            logger.contextualize(service=service.value, instance=config.name),
        ):
            uses_deprecated_hourly_job = hasattr(config.renamarr, "hourly_job")
            if uses_deprecated_hourly_job:
                logger.warning(_DEPRECATED_HOURLY_JOB_WARNING)
            try:
                adapter = create_arr_adapter(
                    service=service,
                    url=config.url,
                    api_key=config.api_key,
                )
                try:
                    Renamarr(
                        name=config.name,
                        adapter=adapter,
                        analyze_files=config.renamarr.analyze_files,
                        rename_folders=config.renamarr.rename_folders,
                        command_polling=config.renamarr.command_polling,
                    ).scan()
                finally:
                    adapter.close()
            except Exception:  # noqa: BLE001 - A failed job must not stop the scheduler.
                logger.exception(
                    "Unexpected failure while running Renamarr for "
                    f"{service.value} instance {config.name!r}."
                )
            finally:
                if uses_deprecated_hourly_job:
                    logger.warning(_DEPRECATED_HOURLY_JOB_WARNING)

    def __schedule_renamarr(
        self, service: ArrService, config: _ArrInstanceConfig
    ) -> None:
        self.__renamarr_job(service, config)

        if config.renamarr.schedule.enabled:
            schedule.every(config.renamarr.schedule.interval.total_minutes).minutes.do(
                self.__renamarr_job, service=service, config=config
            )

    def _run_scheduler_forever(self) -> NoReturn:
        self._health_reporter.idle()
        while True:
            self._health_reporter.heartbeat()
            schedule.run_pending()
            sleep(1)

    def start(self) -> None:
        config_dir = os.getenv("CONFIG_DIR", "/")
        try:
            with set_directory(config_dir):
                config = configparser.get_config(CONFIG_SCHEMA)
        except OSError as exc:
            logger.error(
                f"Unable to access config directory {config_dir!r}; please check volume mount paths or set $CONFIG_DIR."
            )
            logger.error(exc)
            exit(1)
        except ConfigFileNotFoundError as exc:
            logger.error(
                "Unable to locate config file, please check volume mount paths or set $CONFIG_DIR. The default config directory is /config/."
            )
            logger.error(exc)
            exit(1)
        except ConfigError as exc:
            logger.error(
                "Unable to parse config file, Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
            )
            logger.error(exc)
            exit(1)

        service_configs = (
            (ArrService.SONARR, config.sonarr),
            (ArrService.RADARR, config.radarr),
            (ArrService.LIDARR, config.lidarr),
        )
        for service, configs in service_configs:
            instance_config: _ArrInstanceConfig
            for instance_config in configs:
                if instance_config.renamarr.enabled:
                    if instance_config.renamarr.log_to_file:
                        self._logging_configurator.configure_instance_file(
                            service.value, instance_config.name
                        )
                    self.__schedule_renamarr(service, instance_config)
                    continue

                with logger.contextualize(instance=instance_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
                    )

        if schedule.get_jobs():
            self._run_scheduler_forever()


@contextmanager
def set_directory(path: str) -> Iterator[None]:
    oldpwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(oldpwd)


if __name__ == "__main__":  # pragma nocover
    Main().start()  # pragma: no cover
