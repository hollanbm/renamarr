from re import search as regex_search
from os import path
from typing import List

from loguru import logger
from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data
from batch_rename import BatchRename
from rename import Rename


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

                    batch_rename: BatchRename = BatchRename()

                    for episode in self.__aired_episode_list_with_titles(episode_list):
                        file_info = self.sonarr_cli.get_episode_file(
                            episode_id=episode["episodeFileId"]
                        )
                        file_name = path.basename(file_info["path"])
                        season_episode_number = f'S{episode['seasonNumber']:02}E{episode['episodeNumber']:02}'

                        if regex_search(r"\bTBA\b", file_name) is not None:
                            batch_rename.append(
                                Rename(file_info["id"], season_episode_number)
                            )
                            logger.info(f"{season_episode_number} Queing for rename")

                    if batch_rename.has_files_to_rename():
                        self.sonarr_cli.rename_files(
                            batch_rename.get_file_ids(), show.id
                        )
                        logger.info(f"Renaming {batch_rename.get_log_message()}")
                    else:
                        logger.debug("No rename needed")

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
