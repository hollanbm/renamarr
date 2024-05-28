from os import path
from sys import stdout
from time import sleep

import schedule
from config_schema import CONFIG_SCHEMA
from loguru import logger
from pycliarr.api import CliArrError
from pyconfigparser import ConfigError, ConfigFileNotFoundError, configparser
from radarr_renamarr import RadarrRenamarr
from sonarr_renamarr import SonarrRenamarr
from sonarr_series_scanner import SonarrSeriesScanner as SonarrSeriesScanner


class Main:
    """
    This class handles config parsing, and job scheduling
    """

    def __init__(self):
        logger_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{extra[instance]} | "
            "{extra[item]} | "
            "<level>{message}</level>"
        )
        logger.configure(extra={"instance": "", "item": ""})  # Default values
        logger.remove()
        logger.add(stdout, format=logger_format)

    def __sonarr_series_scanner_job(self, sonarr_config):
        try:
            SonarrSeriesScanner(
                name=sonarr_config.name,
                url=sonarr_config.url,
                api_key=sonarr_config.api_key,
                hours_before_air=sonarr_config.series_scanner.hours_before_air,
            ).scan()
        except CliArrError as exc:
            logger.error(exc)

    def __schedule_sonarr_series_scanner(self, sonarr_config):
        self.__sonarr_series_scanner_job(sonarr_config)

        if sonarr_config.series_scanner.hourly_job:
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__sonarr_series_scanner_job, sonarr_config=sonarr_config
            )

    def __sonarr_renamarr_job(self, sonarr_config):
        try:
            SonarrRenamarr(
                name=sonarr_config.name,
                url=sonarr_config.url,
                api_key=sonarr_config.api_key,
                analyze_files=sonarr_config.renamarr.analyze_files,
            ).scan()
        except CliArrError as exc:
            logger.error(exc)

    def __schedule_radarr_renamarr(self, radarr_config):
        self.__radarr_renamarr_job(radarr_config)

        if radarr_config.renamarr.hourly_job:
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__radarr_renamarr_job, radarr_config=radarr_config
            )

    def __radarr_renamarr_job(self, radarr_config):
        try:
            RadarrRenamarr(
                name=radarr_config.name,
                url=radarr_config.url,
                api_key=radarr_config.api_key,
                analyze_files=radarr_config.renamarr.analyze_files,
            ).scan()
        except CliArrError as exc:
            logger.error(exc)

    def __schedule_sonarr_renamarr(self, sonarr_config):
        self.__sonarr_renamarr_job(sonarr_config)

        if sonarr_config.renamarr.hourly_job:
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__sonarr_renamarr_job, sonarr_config=sonarr_config
            )

    def start(self) -> None:
        try:
            config = configparser.get_config(
                CONFIG_SCHEMA,
                config_dir=path.relpath("/config"),
                file_name="config.yml",
            )
        except (ConfigError, ConfigFileNotFoundError) as exc:
            logger.error(exc)
            exit(1)

        for sonarr_config in config.sonarr:
            if not sonarr_config.series_scanner.enabled and not (
                sonarr_config.renamarr.enabled or sonarr_config.existing_renamer.enabled
            ):
                with logger.contextualize(instance=sonarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/docker/config.yml.example"
                    )
                    continue
            if sonarr_config.series_scanner.enabled:
                self.__schedule_sonarr_series_scanner(sonarr_config)
            if sonarr_config.renamarr.enabled:
                self.__schedule_sonarr_renamarr(sonarr_config)
            elif sonarr_config.existing_renamer.enabled:
                logger.warning(
                    "sonarr[].existing_renamer config option, has been renamed to sonarr[].renamarr. Please update config, as this will stop working in future versions"
                )
                logger.warning(
                    "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/docker/config.yml.example"
                )
                self.__schedule_sonarr_renamarr(sonarr_config)

        for radarr_config in config.radarr:
            if radarr_config.renamarr.enabled:
                self.__schedule_radarr_renamarr(radarr_config)
            else:
                with logger.contextualize(instance=radarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/renamarr/blob/main/docker/config.yml.example"
                    )

        if schedule.get_jobs():
            while True:
                schedule.run_pending()
                sleep(1)


if __name__ == "__main__":  # pragma nocover
    Main().start()  # pragma: no cover
