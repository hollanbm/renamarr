import os
from collections.abc import Iterator
from contextlib import contextmanager
from sys import exit, stdout
from time import sleep
from typing import Protocol

import schedule
from dotenv import load_dotenv
from loguru import logger
from pyconfigparser import ConfigError, ConfigFileNotFoundError, configparser

from config_schema import CONFIG_SCHEMA
from interval import Interval
from renamarr.adapter_factory import ArrService, create_arr_adapter
from renamarr.healthcheck.health_reporter import HealthReporter
from renamarr.models import CommandPollingSettings
from renamarr.renamarr import Renamarr

_DEPRECATED_HOURLY_JOB_WARNING: str = (
    "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. "
    "Remove renamarr.hourly_job after migrating the schedule configuration."
)


class _ScheduleConfig(Protocol):
    enabled: bool
    interval: Interval


class _RenamarrConfig(Protocol):
    analyze_files: bool
    rename_folders: bool
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

    RUN_SCHEDULER = True
    _LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level}</level> | "
        "{extra[instance]} | "
        "{extra[item]} | "
        "<level>{message}</level>"
    )
    _DEBUG_LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[instance]} | "
        "{extra[item]} | "
        "<level>{message}</level>"
    )

    def __init__(self) -> None:
        load_dotenv(".env.local")
        log_level = os.getenv("LOG_LEVEL", "INFO")

        self._health_reporter = HealthReporter()
        self._logger_format = (
            self._DEBUG_LOG_FORMAT if log_level.upper() == "DEBUG" else self._LOG_FORMAT
        )
        logger.configure(extra={"instance": "", "item": ""})  # Default values
        logger.remove()
        logger.add(stdout, format=self._logger_format, level=log_level)

    def __configure_file_logging(self, service: str, instance_name: str) -> bool:
        log_dir = os.getenv("LOG_DIR", "/logs")
        log_rotation = os.getenv("LOG_ROTATION", "00:00")
        log_retention = os.getenv("LOG_RETENTION", "7 days")
        log_path = os.path.join(log_dir, service, f"{instance_name}.log")
        try:
            logger.add(
                log_path,
                format=self._logger_format,
                level=os.getenv("LOG_LEVEL", "INFO"),
                rotation=log_rotation,
                retention=log_retention,
                # filter ensures that instance logs go to the correct file
                filter=lambda record, configured_service=service, configured_name=instance_name: (
                    record["extra"].get("service") == configured_service
                    and record["extra"].get("instance") == configured_name
                ),
            )
        except OSError as exc:
            with logger.contextualize(service=service, instance=instance_name):
                logger.warning(
                    f"Unable to write logs to {log_path!r}; continuing with stdout logging only."
                )
                logger.warning(exc)
            return False
        return True

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
                Renamarr(
                    name=config.name,
                    adapter=adapter,
                    analyze_files=config.renamarr.analyze_files,
                    rename_folders=config.renamarr.rename_folders,
                    command_polling=config.renamarr.command_polling,
                ).scan()
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

        for sonarr_config in config.sonarr:
            if not sonarr_config.renamarr.enabled:
                with logger.contextualize(instance=sonarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
                    )
                    continue
            if sonarr_config.renamarr.log_to_file:
                self.__configure_file_logging("sonarr", sonarr_config.name)
            self.__schedule_renamarr(ArrService.SONARR, sonarr_config)

        for radarr_config in config.radarr:
            if radarr_config.renamarr.enabled:
                if radarr_config.renamarr.log_to_file:
                    self.__configure_file_logging("radarr", radarr_config.name)
                self.__schedule_renamarr(ArrService.RADARR, radarr_config)
            else:
                with logger.contextualize(instance=radarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
                    )

        if schedule.get_jobs():
            self._health_reporter.idle()
            while self.RUN_SCHEDULER:
                self._health_reporter.heartbeat()
                schedule.run_pending()
                sleep(1)


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
