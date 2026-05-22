from pathlib import PurePosixPath
from time import sleep

from loguru import logger
from pycliarr.api import RadarrCli, RadarrMovieItem
from pycliarr.api.base_api import json_data, json_dict

from renamarr.radarr.models.folder_rename_plan import RadarrFolderRenamePlan


class MovieFolderRename:
    """Service for renaming Radarr movie folders."""

    def __init__(self, radarr_cli: RadarrCli) -> None:
        self.radarr_cli = radarr_cli

    def process(self, movies: list[RadarrMovieItem]) -> None:
        """Rename movie folders for movies whose path differs from Radarr's expected folder."""
        folder_rename_plan = self.__build_folder_rename_plan(movies)

        if not folder_rename_plan.has_folder_renames():
            return

        logger.debug("Processing pending movie folder renames")
        for root_folder_rename in folder_rename_plan.root_folder_renames:
            movie_titles = folder_rename_plan.get_movie_titles(root_folder_rename)
            movie_ids = folder_rename_plan.get_movie_ids(root_folder_rename)

            multiple_movies = len(movie_ids) > 1
            logger.info(
                f"Renaming Movie {'folders' if multiple_movies else 'folder'} "
                f"for {'movies' if multiple_movies else 'movie'}: {movie_titles}"
            )
            folder_rename_response = self.radarr_cli._session.request(
                "PUT",
                f"{self.radarr_cli.host_url}/api/v3/movie/editor",
                json=dict(
                    rootFolderPath=root_folder_rename.root_folder_path,
                    movieIds=movie_ids,
                    moveFiles=root_folder_rename.move_files,
                ),
            )
            if not 200 <= folder_rename_response.status_code <= 299:
                logger.error(
                    f"Movie folder rename failed for movies: {movie_titles}: "
                    f"status code {folder_rename_response.status_code}"
                )
                continue

            logger.info(f"Movie folder rename successful for movies: {movie_titles}")
            logger.info("Initiated disk scan of updated movies")

            if self.__rescan_movies(movie_ids):
                logger.info("disk scan finished successfully")
            else:
                logger.info("disk scan failed")

    def __build_folder_rename_plan(
        self, movies: list[RadarrMovieItem]
    ) -> RadarrFolderRenamePlan:
        folder_rename_plan = RadarrFolderRenamePlan()
        radarr_root_folders: list[json_dict] = self.radarr_cli.get_root_folder()

        for movie in movies:
            with logger.contextualize(item=movie.title):
                current_movie_path = PurePosixPath(movie.path)
                movie_root_folder = self.__find_movie_root_folder(
                    current_movie_path, radarr_root_folders
                )

                if movie_root_folder is None:
                    logger.warning(
                        f"Unable to determine matching Radarr root folder for movie path {current_movie_path}"
                    )
                    continue

                expected_folder_name: str = self.radarr_cli.request_get(
                    path=f"/api/v3/movie/{movie.id}/folder"
                )["folder"]
                movie_root_folder_path = movie_root_folder["path"]

                expected_movie_folder_path = (
                    PurePosixPath(movie_root_folder_path) / expected_folder_name
                )

                if expected_movie_folder_path != current_movie_path:
                    folder_rename_plan.add_movie(movie_root_folder_path, movie)
                    logger.debug("added movie to pending folder_rename_plan operation")

        return folder_rename_plan

    def __find_movie_root_folder(
        self,
        current_movie_path: PurePosixPath,
        radarr_root_folders: list[json_dict],
    ) -> json_dict | None:
        """Return the Radarr root folder whose path is a parent of the movie path."""
        for root_folder in radarr_root_folders:
            root_folder_path = PurePosixPath(root_folder["path"])

            if root_folder_path in current_movie_path.parents:
                return root_folder

        return None

    def __rescan_movies(self, movie_ids: list[int]) -> bool:
        """Rescan the Radarr movies that were moved."""
        rescan_command = self.radarr_cli._sendCommand(
            {
                "priority": "high",
                "name": "RefreshMovie",
                "movieIds": movie_ids,
            }
        )
        resp: json_data = {}

        while resp.get("status") != "completed":
            sleep(10)
            resp = self.radarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"
