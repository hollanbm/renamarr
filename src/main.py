import os
from collections.abc import Callable
from contextlib import contextmanager
from time import perf_counter
from time import sleep
from time import time

import schedule
from dotenv import load_dotenv
from loguru import logger
from pycliarr.api import CliArrError
from pyconfigparser import ConfigError, ConfigFileNotFoundError, configparser

from config_schema import CONFIG_SCHEMA
from renamarr.logging_config import LoggingConfigurator
from renamarr.otel.job_result import JobResult
from renamarr.otel.observability import configure_observability
from renamarr.otel.service_name import ServiceName
from renamarr.radarr.services.renamarr import RadarrRenamarr
from renamarr.sonarr.services.renamarr import SonarrRenamarr
from renamarr.sonarr.services.series_scanner import SonarrSeriesScanner


class Main:
    """
    This class handles config parsing, and job scheduling
    """

    RUN_SCHEDULER = True

    def __init__(self):
        load_dotenv(".env.local")
        self._logging_configurator = LoggingConfigurator()
        self._logging_configurator.configure_stdout()
        self.observability = configure_observability()

    def __external_cron(self) -> bool:
        return os.getenv("EXTERNAL_CRON", "false").lower() == "true"

    def __run_observed_job(
        self,
        service: ServiceName,
        instance_name: str,
        job_name: str,
        job: Callable[[], None],
    ) -> None:
        start_time = perf_counter()
        self.observability.record_job_started(
            service,
            instance_name,
            job_name,
            time(),
        )
        result = JobResult.SUCCESS
        try:
            with self.observability.start_span(
                f"renamarr.job.{service}.{job_name}",
                attributes={
                    "service": service,
                    "name": instance_name,
                    "job": job_name,
                },
            ):
                job()
        except CliArrError as exc:
            result = JobResult.FAILED
            logger.error(exc)
        except Exception:
            result = JobResult.FAILED
            raise
        finally:
            self.observability.record_job(
                service,
                instance_name,
                job_name,
                result,
                perf_counter() - start_time,
            )
            self.observability.force_flush()

    def __sonarr_series_scanner_job(self, sonarr_config):
        with logger.contextualize(
            service=ServiceName.SONARR, instance=sonarr_config.name
        ):
            self.__run_observed_job(
                ServiceName.SONARR,
                sonarr_config.name,
                "series_scanner",
                lambda: SonarrSeriesScanner(
                    name=sonarr_config.name,
                    url=sonarr_config.url,
                    api_key=sonarr_config.api_key,
                    hours_before_air=sonarr_config.series_scanner.hours_before_air,
                ).scan(),
            )

    def __schedule_sonarr_series_scanner(self, sonarr_config):
        self.__sonarr_series_scanner_job(sonarr_config)

        if sonarr_config.series_scanner.hourly_job and not self.__external_cron():
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__sonarr_series_scanner_job, sonarr_config=sonarr_config
            )

    def __sonarr_renamarr_job(self, sonarr_config):
        with logger.contextualize(
            service=ServiceName.SONARR, instance=sonarr_config.name
        ):
            self.__run_observed_job(
                ServiceName.SONARR,
                sonarr_config.name,
                "renamarr",
                lambda: SonarrRenamarr(
                    name=sonarr_config.name,
                    url=sonarr_config.url,
                    api_key=sonarr_config.api_key,
                    analyze_files=sonarr_config.renamarr.analyze_files,
                    rename_folders=sonarr_config.renamarr.rename_folders,
                ).scan(),
            )

    def __schedule_radarr_renamarr(self, radarr_config):
        self.__radarr_renamarr_job(radarr_config)

        if radarr_config.renamarr.hourly_job and not self.__external_cron():
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__radarr_renamarr_job, radarr_config=radarr_config
            )

    def __radarr_renamarr_job(self, radarr_config):
        with logger.contextualize(
            service=ServiceName.RADARR, instance=radarr_config.name
        ):
            self.__run_observed_job(
                ServiceName.RADARR,
                radarr_config.name,
                "renamarr",
                lambda: RadarrRenamarr(
                    name=radarr_config.name,
                    url=radarr_config.url,
                    api_key=radarr_config.api_key,
                    analyze_files=radarr_config.renamarr.analyze_files,
                    rename_folders=radarr_config.renamarr.rename_folders,
                ).scan(),
            )

    def __schedule_sonarr_renamarr(self, sonarr_config):
        self.__sonarr_renamarr_job(sonarr_config)

        if sonarr_config.renamarr.hourly_job and not self.__external_cron():
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__sonarr_renamarr_job, sonarr_config=sonarr_config
            )

    def __start(self) -> None:
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
            if not (
                sonarr_config.series_scanner.enabled or sonarr_config.renamarr.enabled
            ):
                with logger.contextualize(instance=sonarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
                    )
                    continue
            if sonarr_config.series_scanner.enabled:
                self.__schedule_sonarr_series_scanner(sonarr_config)
            if sonarr_config.renamarr.enabled:
                if sonarr_config.renamarr.log_to_file:
                    self._logging_configurator.configure_instance_file(
                        ServiceName.SONARR, sonarr_config.name
                    )
                self.__schedule_sonarr_renamarr(sonarr_config)

        for radarr_config in config.radarr:
            if radarr_config.renamarr.enabled:
                if radarr_config.renamarr.log_to_file:
                    self._logging_configurator.configure_instance_file(
                        ServiceName.RADARR, radarr_config.name
                    )
                self.__schedule_radarr_renamarr(radarr_config)
            else:
                with logger.contextualize(instance=radarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/example/config.yml.example"
                    )

        if schedule.get_jobs():
            while self.RUN_SCHEDULER:
                schedule.run_pending()
                sleep(1)

    def start(self) -> None:
        try:
            self.__start()
        finally:
            self.observability.shutdown()


@contextmanager
def set_directory(path):
    oldpwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(oldpwd)


if __name__ == "__main__":  # pragma nocover
    Main().start()  # pragma: no cover
