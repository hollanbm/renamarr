from typing import List

from loguru import logger
from models.batch_rename import BatchRename
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

            if len(series) == 0:
                logger.error("Sonarr returned empty series list")
            else:
                logger.debug("Retrieved series list")

            for show in sorted(series, key=lambda s: s.title):
                with logger.contextualize(series=show.title):
                    episodes_to_rename: List[json_data] = self.sonarr_cli.request_get(
                        path="/api/v3/rename",
                        url_params=dict(seriesId=show.id),
                    )

                    if len(episodes_to_rename) == 0:
                        logger.debug("No episodes to rename")
                    else:
                        batch_rename: BatchRename = BatchRename()

                        for episode in episodes_to_rename:
                            logger.debug("Found episodes to be renamed")

                            batch_rename.append(
                                file_id=episode["episodeFileId"],
                                season_number=episode["seasonNumber"],
                                episode_numbers=episode["episodeNumbers"],
                            )

                        logger.info(f"Renaming {batch_rename.get_log_message()}")

                        self.sonarr_cli.rename_files(
                            batch_rename.get_file_ids(), show.id
                        )

            logger.info("Finished Existing Renamer")
