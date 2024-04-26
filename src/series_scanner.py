from os import environ
from datetime import datetime, timezone, timedelta
from dateutil import parser
from pycliarr.api import SonarrCli
from loguru import logger


def scan():
    logger.info("Starting Series Scam")

    sonarr_cli = SonarrCli(environ["SONARR_URL"], environ["SONARR_API_KEY"])

    series = sonarr_cli.get_serie()

    if series is []:
        logger.error("Sonarr returned empty series list")
        exit(0)
    else:
        logger.debug("Retrieved series list")

    for show in sorted(series, key=lambda s: s.title):
        if show.status.lower() == "continuing":
            episode_list = sonarr_cli.get_episode(show.id)

            if episode_list is []:
                logger.error(f"{show.title} - Error fetching episode list")
                exit(1)
            else:
                logger.debug(f"{show.title} - Retrieved episode list")

            for episode in __filter_episode_list(episode_list):
                episode_air_date_utc = parser.parse(episode["airDateUtc"]).astimezone(
                    timezone.utc
                )

                if __is_episode_airing_soon(episode_air_date_utc):
                    logger.info(
                        f"{show.title} - Found episode aired/airing with TBA title"
                    )
                    sonarr_cli.refresh_serie(show.id)
                    logger.info(f"{show.title} - Series rescan triggered")
                    break

    logger.info("Finished Series Scam")


# Filter episode list, so it only contains episodes with TBA title
def __filter_episode_list(episode_list):
    """
    Filters episode list, removing all episodes that have a title, or no airDate

    Parameters:
      episode_list (List[SonarrSerieItem]):The episode list to be filered.

    Returns:
      List[SonarrSerieItem]
    """
    return [
        e
        for e in episode_list
        if e.get("seasonNumber") > 0
        and e.get("title") == "TBA"
        and e.get("airDateUtc") != None
    ]


def __is_episode_airing_soon(episode_air_date_utc):
    """
    Parameters:
      episode_air_date_utc (datetime):The episode air date with utc timezone

    Returns:
      bool True if episode is airing within environ['HOURS_BEFORE_AIR'], or True if episode has already aired
    """
    hours_before_air = -min(int(environ["HOURS_BEFORE_AIR"]) or 4, 12)
    return (
        datetime.now(timezone.utc) - episode_air_date_utc
    ).total_seconds() / 3600 >= hours_before_air