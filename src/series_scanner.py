from datetime import datetime, timezone
from dateutil import parser
from pycliarr.api import SonarrCli
from loguru import logger


class SeriesScanner:
    def __init__(self, name, url, api_key, hours_before_air):
        self.name = name
        self.url = url
        self.api_key = api_key
        self.hours_before_air = min(hours_before_air, 12)

    def scan(self):
        with logger.contextualize(instance=self.name):
            logger.info("Starting Series Scan")

            sonarr_cli = SonarrCli(self.url, self.api_key)

            series = sonarr_cli.get_serie()

            if series is []:
                logger.error("Sonarr returned empty series list")
            else:
                logger.debug("Retrieved series list")

            for show in sorted(series, key=lambda s: s.title):
                with logger.contextualize(series=show.title):
                    if show.status.lower() == "continuing":
                        episode_list = sonarr_cli.get_episode(show.id)

                        if episode_list is []:
                            logger.error("Error fetching episode list")
                            continue
                        else:
                            logger.debug("Retrieved episode list")

                        for episode in self.__filter_episode_list(episode_list):
                            episode_air_date_utc = parser.parse(
                                episode["airDateUtc"]
                            ).astimezone(timezone.utc)

                            if self.__is_episode_airing_soon(episode_air_date_utc):
                                logger.info(
                                    f"Found TBA episode, airing within the next {self.hours_before_air} hours"
                                )
                                sonarr_cli.refresh_serie(show.id)
                                logger.info("Series rescan triggered")
                                break
                            elif self.__has_episode_already_aired(episode_air_date_utc):
                                logger.info(
                                    "Found previously aired episode with TBA title"
                                )
                                sonarr_cli.refresh_serie(show.id)
                                logger.info("Series rescan triggered")
                                break
                        logger.debug("Finished Processing")

            logger.info("Finished Series Scam")

    # Filter episode list, so it only contains episodes with TBA title
    def __filter_episode_list(self, episode_list):
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
            and e.get("airDateUtc") is not None
        ]

    def __is_episode_airing_soon(self, episode_air_date_utc):
        """
        Parameters:
        episode_air_date_utc (datetime):The episode air date with utc timezone

        Returns:
        bool True if episode is airing within config.sonarr[].series_scanner.hours_before_air
        """

        hours_till_airing = (
            episode_air_date_utc - datetime.now(timezone.utc)
        ).total_seconds() / 3600

        return hours_till_airing <= self.hours_before_air

    def __has_episode_already_aired(self, episode_air_date_utc):
        """
        Parameters:
        episode_air_date_utc (datetime):The episode air date with utc timezone

        Returns:
        bool True if episode has already aired
        """

        return (datetime.now(timezone.utc) - episode_air_date_utc).total_seconds() > 0
