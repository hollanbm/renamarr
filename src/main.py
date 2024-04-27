from series_scanner import SeriesScanner
from config.schema import CONFIG_SCHEMA
from loguru import logger
from os import environ
from os import path
from pycliarr.api import CliServerError
from pyconfigparser import configparser, ConfigError, ConfigFileNotFoundError

import schedule
from time import sleep
from sys import stdout


def job(sonarr_config):
    try:
        SeriesScanner(
            name=sonarr_config.name,
            url=sonarr_config.url,
            api_key=sonarr_config.api_key,
            hours_before_air=sonarr_config.series_scanner.hours_before_air,
        ).scan()
    except CliServerError as exc:
        logger.error(exc)


def schedule_series_scanner(sonarr_config):
    job(sonarr_config)

    if sonarr_config.series_scanner.hourly_job:
        # Add a random delay of +-5 minutes between jobs
        schedule.every(55).to(65).minutes.do(job, sonarr_config=sonarr_config)


def loguru_config():
    environ["LOGURU_LEVEL"] = "DEBUG"  # environ.get("LOG_LEVEL") or "INFO"

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


if __name__ == "__main__":
    loguru_config()

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
        if sonarr_config.series_scanner.enabled:
            schedule_series_scanner(sonarr_config)

    if schedule.get_jobs():
        while True:
            schedule.run_pending()
            sleep(1)
