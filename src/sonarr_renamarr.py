from dataclasses import asdict
from time import sleep
from typing import List

from loguru import logger
from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data, json_dict

from models.batch_rename import BatchRename
from models.bulk_move import BulkMove


class SonarrRenamarr:
    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        analyze_files: bool = False,
        rename_folders=True,
    ):
        self.name = name
        self.sonarr_cli = SonarrCli(url, api_key)
        self.analyze_files = analyze_files
        self.rename_files = rename_folders
        self.bulk_move = BulkMove()

    def scan(self):
        with logger.contextualize(instance=self.name):
            logger.info("Starting Renamarr")

            bulk_move = BulkMove()

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

            series = self.sonarr_cli.get_serie()

            if len(series) == 0:
                logger.error("Sonarr returned empty series list")
            else:
                logger.debug("Retrieved series list")

            for show in sorted(series, key=lambda s: s.title):
                with logger.contextualize(item=show.title):
                    if self.rename_files:
                        root_folders: List[json_dict] = (
                            self.sonarr_cli.get_root_folder()
                        )

                        series_folder: str = self.sonarr_cli.request_get(
                            path=f"/api/v3/series/{show.id}/folder"
                        )["folder"]

                        for root_folder in root_folders:
                            root_folder_path = root_folder["path"]
                            if (
                                root_folder_path in show.path
                                and f"{root_folder_path}/{series_folder}" == show.path
                            ):
                                bulk_move.add(root_folder_path, show.id)
                                logger.debug(
                                    "added series to pending bulk_move operation"
                                )

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

                        if bulk_move.has_pending_moves():
                            logger.debug("Processing pending series folder renames")
                            for move in bulk_move.pending_moves:
                                logger.info(
                                    f"Renaming Series folder for series IDs: {', '.join(str(series_id) for series_id in move.seriesIds)}"
                                )
                                self.sonarr_cli.request_put(
                                    path="/api/v3/series/editor", json_data=asdict(move)
                                )

            logger.info("Finished Renamarr")

    def __analyze_files(self) -> bool:
        """_summary_

        Returns:
            bool: if disk scan succeeded
        """
        rescan_command = self.sonarr_cli._sendCommand(
            {
                "name": "RescanSeries",
                "priority": "high",
            }
        )
        resp: json_data = {}

        # sonarr commands have to be polled for completion status
        while resp.get("status") != "completed":
            sleep(10)
            resp = self.sonarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"

    def __analyze_files_enabled(self) -> bool:
        """_summary_

        Returns:
            bool: if analyze_files is enabled
        """
        mediamanagement: json_data = self.sonarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
