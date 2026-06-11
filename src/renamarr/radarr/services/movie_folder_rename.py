import time
from pathlib import PurePosixPath
from time import sleep

from loguru import logger
from pycliarr.api import RadarrCli, RadarrMovieItem
from pycliarr.api.base_api import json_data, json_dict

from renamarr.observability import get_observability
from renamarr.radarr.models.folder_rename_plan import RadarrFolderRenamePlan

MAX_WAIT_SECONDS = 5 * 60


class MovieRootFolderNotFoundError(Exception):
    """Raised when a Radarr movie path does not match any configured root folder."""


class MovieFolderRename:
    """Service for renaming Radarr movie folders."""

    def __init__(self, radarr_cli: RadarrCli, name: str = "") -> None:
        self.radarr_cli = radarr_cli
        self.name = name

    def process(self, movies: list[RadarrMovieItem]) -> None:
        """Rename movie folders for movies whose path differs from Radarr's expected folder."""
        observability = get_observability()
        with observability.start_span(
            "renamarr.radarr.folder_rename",
            attributes={
                "service": "radarr",
                "name": self.name,
                "operation": "folder_rename",
            },
        ):
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
                try:
                    folder_rename_response = self.radarr_cli._session.request(
                        "PUT",
                        f"{self.radarr_cli.host_url}/api/v3/movie/editor",
                        json=dict(
                            rootFolderPath=root_folder_rename.root_folder_path,
                            movieIds=movie_ids,
                            moveFiles=root_folder_rename.move_files,
                        ),
                    )
                except Exception:
                    observability.record_operation_items(
                        "radarr",
                        "folder_rename",
                        self.name,
                        "failed",
                        len(movie_ids),
                    )
                    raise
                if not 200 <= folder_rename_response.status_code <= 299:
                    observability.record_operation_items(
                        "radarr",
                        "folder_rename",
                        self.name,
                        "failed",
                        len(movie_ids),
                    )
                    logger.error(
                        f"Movie folder rename failed for movies: {movie_titles}: "
                        f"status code {folder_rename_response.status_code}"
                    )
                    continue

                observability.record_operation_items(
                    "radarr",
                    "folder_rename",
                    self.name,
                    "accepted",
                    len(movie_ids),
                )
                logger.info(
                    f"Movie folder rename successful for movies: {movie_titles}"
                )
                logger.info("Initiated disk scan of updated movies")

                if self.__rescan_movies(movie_ids):
                    logger.info("disk scan finished successfully")
                else:
                    logger.info("disk scan failed")

    def __build_folder_rename_plan(
        self, movies: list[RadarrMovieItem]
    ) -> RadarrFolderRenamePlan:
        folder_rename_plan = RadarrFolderRenamePlan()
        radarr_root_folders: list[json_dict] = sorted(
            self.radarr_cli.get_root_folder(),
            key=lambda root_folder: root_folder["path"],
        )

        for movie in movies:
            with logger.contextualize(item=movie.title):
                current_movie_path = PurePosixPath(movie.path)

                try:
                    movie_root_folder = self.__find_movie_root_folder(
                        current_movie_path, radarr_root_folders
                    )
                except MovieRootFolderNotFoundError as error:
                    logger.error(str(error))
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
    ) -> json_dict:
        """Return the deepest Radarr root folder matching the movie path.

        PurePosixPath parent matching compares path parts, so sibling root folders
        with overlapping names like /movies and /movies-4k do not collide. When
        Radarr has nested roots like /data/media and /data/media/movies, both can
        match the same movie path; the deepest match preserves the movie's actual
        root folder.

        Raises:
            MovieRootFolderNotFoundError: If Radarr has no root folder matching the
                movie path.
        """

        # Nested root folders are a valid Radarr configuration
        # This makes it possible for a movie to match multiple root folders
        # collect all matches, so that we can select the best match, instead of the first match
        matching_root_folders: list[tuple[PurePosixPath, json_dict]] = []
        for root_folder in radarr_root_folders:
            root_folder_path = PurePosixPath(root_folder["path"])

            if (
                root_folder_path == current_movie_path
                or root_folder_path in current_movie_path.parents
            ):
                matching_root_folders.append((root_folder_path, root_folder))

        if not matching_root_folders:
            raise MovieRootFolderNotFoundError(
                f"Unable to determine matching Radarr root folder for movie path {current_movie_path}"
            )

        return max(matching_root_folders, key=lambda match: len(match[0].parts))[1]

    def __rescan_movies(self, movie_ids: list[int]) -> bool:
        """Rescan the Radarr movies that were moved."""
        start = time.time()
        rescan_command = self.radarr_cli._sendCommand(
            {
                "priority": "high",
                "name": "RefreshMovie",
                "movieIds": movie_ids,
            }
        )
        resp: json_data = {}

        while resp.get("status") != "completed":
            if time.time() - start >= MAX_WAIT_SECONDS:
                logger.error(
                    f"Timed out waiting for Radarr movie rescan command {rescan_command['id']} "
                    f"after {MAX_WAIT_SECONDS} seconds"
                )
                return False
            sleep(10)
            resp = self.radarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"
