from os import path
from sys import stdout
from time import sleep

import schedule
from config_schema import CONFIG_SCHEMA
from existing_renamer import ExistingRenamer
from loguru import logger
from pycliarr.api import CliArrError
from pyconfigparser import ConfigError, ConfigFileNotFoundError, configparser
from series_scanner import SeriesScanner


class Main:
    def __init__(self):
        logger_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "{extra[instance]} | "
            "{extra[series]} | "
            "<level>{message}</level>"
        )
        logger.configure(extra={"instance": "", "series": ""})  # Default values
        logger.remove()
        logger.add(stdout, format=logger_format)

    def __series_scanner_job(self, sonarr_config):
        try:
            SeriesScanner(
                name=sonarr_config.name,
                url=sonarr_config.url,
                api_key=sonarr_config.api_key,
                hours_before_air=sonarr_config.series_scanner.hours_before_air,
            ).scan()
        except CliArrError as exc:
            logger.error(exc)

    def __schedule_series_scanner(self, sonarr_config):
        self.__series_scanner_job(sonarr_config)

        if sonarr_config.series_scanner.hourly_job:
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__series_scanner_job, sonarr_config=sonarr_config
            )

    def __existing_renamer_job(self, sonarr_config):
        try:
            ExistingRenamer(
                name=sonarr_config.name,
                url=sonarr_config.url,
                api_key=sonarr_config.api_key,
            ).scan()
        except CliArrError as exc:
            logger.error(exc)

    def __schedule_existing_renamer(self, sonarr_config):
        self.__existing_renamer_job(sonarr_config)

        if sonarr_config.existing_renamer.hourly_job:
            # Add a random delay of +-5 minutes between jobs
            schedule.every(55).to(65).minutes.do(
                self.__existing_renamer_job, sonarr_config=sonarr_config
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
            if (
                not sonarr_config.series_scanner.enabled
                and not sonarr_config.existing_renamer.enabled
            ):
                with logger.contextualize(instance=sonarr_config.name):
                    logger.warning(
                        "Possible config error? -- No jobs configured for current instance"
                    )
                    logger.warning(
                        "Please see example config for comparison -- https://github.com/hollanbm/sonarr-series-scanner/blob/main/docker/config.yml.example"
                    )
                    continue
            if sonarr_config.series_scanner.enabled:
                self.__schedule_series_scanner(sonarr_config)
            if sonarr_config.existing_renamer.enabled:
                self.__schedule_existing_renamer(sonarr_config)

        if schedule.get_jobs():
            while True:
                schedule.run_pending()
                sleep(1)


if __name__ == "__main__":
    Main().start()
