from dataclasses import asdict
from pathlib import PurePosixPath
from time import sleep

from loguru import logger
from pycliarr.api import RadarrCli
from pycliarr.api.base_api import json_data, json_dict

from models.radarr_bulk_move import RadarrBulkMove


class RadarrRenamarr:
    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        analyze_files: bool = False,
        rename_folders: bool = False,
    ):
        self.name = name
        self.radarr_cli = RadarrCli(url, api_key)
        self.analyze_files = analyze_files
        self.rename_folders = rename_folders

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

            bulk_move = RadarrBulkMove()
            root_folders: list[json_dict] = []
            if self.rename_folders and len(movies) > 0:
                root_folders = self.radarr_cli.get_root_folder()

            for movie in sorted(movies, key=lambda m: m.title):
                with logger.contextualize(item=movie.title):
                    if self.rename_folders:
                        movie_folder: str = self.radarr_cli.request_get(
                            path=f"/api/v3/movie/{movie.id}/folder"
                        )["folder"]

                        movie_path = PurePosixPath(movie.path)

                        for root_folder in root_folders:
                            root_folder_path = root_folder["path"]
                            root_path = PurePosixPath(root_folder_path)
                            expected_movie_path = root_path / movie_folder

                            if (
                                root_path in movie_path.parents
                                and expected_movie_path != movie_path
                            ):
                                bulk_move.add(root_folder_path, movie.id)
                                logger.debug(
                                    "added movie to pending bulk_move operation"
                                )

                    files_to_rename: list[json_data] = self.radarr_cli.request_get(
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

            if bulk_move.has_pending_moves():
                logger.debug("Processing pending movie folder renames")
                for move in bulk_move.pending_moves:
                    movie_ids_message = ", ".join(
                        str(movie_id) for movie_id in move.movieIds
                    )
                    logger.info(
                        f"Renaming Movie folder for movie IDs: {movie_ids_message}"
                    )
                    self.radarr_cli.request_put(
                        path="/api/v3/movie/editor",
                        json_data=asdict(move),
                    )

                    logger.info(
                        f"Movie folder rename successful for movie IDs: {movie_ids_message}"
                    )

                    logger.info("Initiated disk scan of library")
                    if self.__analyze_files():
                        logger.info("disk scan finished successfully")
                    else:
                        logger.info("disk scan failed")

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
