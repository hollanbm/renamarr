from os import path
from typing import List

from loguru import logger
from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data


class ExistingRenamer:
    def __init__(self, name, url, api_key):
        self.name = name
        self.sonarr_cli = SonarrCli(url, api_key)

    def scan(self):
        with logger.contextualize(instance=self.name):
            logger.info("Starting Existing Renamer")

            series = self.sonarr_cli.get_serie()

            if series is []:
                logger.error("Sonarr returned empty series list")
            else:
                logger.debug("Retrieved series list")
            for show in sorted(series, key=lambda s: s.title):
                with logger.contextualize(series=show.title):
                    episode_list = self.sonarr_cli.get_episode(show.id)

                    if episode_list is []:
                        logger.error("Error fetching episode list")
                        continue
                    else:
                        logger.debug("Retrieved episode list")
                    # generic dict, used to batch up files for renaming, as well as a user friendly output for logging
                    files_to_rename: dict = {"episode_ids": [], "log_msg": []}

                    for episode in self.__aired_episode_list_with_titles(episode_list):
                        file_info = self.sonarr_cli.get_episode_file(
                            episode_id=episode["id"]
                        )
                        season_episode_number = f'S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}'

                        # file on disk, doesn't contain episode name
                        if episode["title"] not in path.basename(file_info["path"]):
                            files_to_rename["episode_ids"].append(file_info["id"])
                            files_to_rename["log_msg"].append(season_episode_number)
                            logger.info(
                                f"{season_episode_number} filename does not contain episode name"
                            )
                            logger.info(f"{season_episode_number} Queing for rename")

                    # TODO: Submit PR to original repo updating rename payload for episode rename method to work
                    self.sonarr_cli._sendCommand(
                        {
                            "name": "RenameFiles",
                            "files": files_to_rename["episode_ids"],
                            "seriesId": show.id,
                        }
                    )

                    logger.info(f'Renaming {', '.join(files_to_rename["log_msg"])}')
                logger.info("Finished Existing Renamer")

    def __aired_episode_list_with_titles(self, episode_list: List[json_data]):
        """
        Filters episode list, removing all episodes that have not aired

        Parameters:
        episode_list (List[json_data]):The episode list to be filered.

        Returns:
        List[json_data]
        """
        return sorted(
            [
                e
                for e in episode_list
                if e.get("seasonNumber") > 0
                and e.get("title") != "TBA"
                and e.get("hasFile")
            ],
            key=lambda e: e.get("episodeNumber"),
        )
