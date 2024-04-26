import series_scanner

from datetime import timedelta
from dotenv import load_dotenv
from loguru import logger
from os import environ
from pycliarr.api import CliServerError
from scheduler import Scheduler
from time import sleep


def job():
    try:
        series_scanner.scan()
    except CliServerError as exc:
        logger.error(exc)


if __name__ == "__main__":
    load_dotenv()

    if environ.get("SONARR_URL") is None:
        logger.error("SONARR_URL not set")
        exit(1)

    if environ.get("SONARR_API_KEY") is None:
        logger.error("SONARR_API_KEY not set")
        exit(1)

    job()

    if environ["HOURLY_JOB"].lower() in ("y", "yes", "t", "true", "on", "1"):
        # schedule job hourly
        schedule = Scheduler()
        schedule.cyclic(timedelta(hours=1), job)

        while True:
            schedule.exec_jobs()
            sleep(1)
