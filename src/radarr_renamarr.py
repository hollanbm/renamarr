from time import sleep
from typing import List

from loguru import logger
from pycliarr.api import RadarrCli
from pycliarr.api.base_api import json_data


class RadarrRenamarr:
    def __init__(self, name: str, url: str, api_key: str, analyze_files: bool = False):
        self.name = name
        self.radarr_cli = RadarrCli(url, api_key)
        self.analyze_files = analyze_files

    def scan(self):
        with logger.contextualize(instance=self.name):
            logger.info("Starting Renamarr")

            if self.analyze_files:
                if not self.__analyze_files_enabled():
                    logger.warning(
                        "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
                    )
                else:
                    logger.info("Initiated disk scan of library")
                    if self.__analyze_files():
                        logger.info("disk scan finished successfully")
                    else:
                        logger.info("disk scan failed")

            movies = self.radarr_cli.get_movie()

            if len(movies) == 0:
                logger.error("Radarr returned empty movie list")
            else:
                logger.debug("Retrieved movie list")

            for movie in sorted(movies, key=lambda m: m.title):
                with logger.contextualize(item=movie.title):
                    files_to_rename: List[json_data] = self.radarr_cli.request_get(
                        path="/api/v3/rename",
                        url_params=dict(movieId=movie.id),
                    )

                    if len(files_to_rename) == 0:
                        logger.debug("Nothing to rename")
                    else:
                        logger.debug("Initiating rename")

                        for file in files_to_rename:
                            self.radarr_cli._sendCommand(
                                dict(
                                    name="RenameFiles",
                                    files=[file.get("movieFileId")],
                                    movieId=file.get("movieId"),
                                )
                            )

                        logger.info("Renamed")

            logger.info("Finished Renamarr")

    def __analyze_files(self) -> bool:
        """_summary_

        Returns:
            bool: if disk scan succeeded
        """
        rescan_command = self.radarr_cli._sendCommand(
            {
                "name": "RescanMovie",
                "priority": "high",
            }
        )
        resp: json_data = {}

        # Radarr commands have to be polled for completion status
        while resp.get("status") != "completed":
            sleep(10)
            resp = self.radarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"

    def __analyze_files_enabled(self) -> bool:
        """_summary_

        Returns:
            bool: if analyze_files is enabled
        """
        mediamanagement: json_data = self.radarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
