from loguru import logger
from pycliarr.api import RadarrCli, RadarrMovieItem
from pycliarr.api.base_api import json_data

from renamarr.observability import (
    OperationName,
    OperationResult,
    ServiceName,
    get_observability,
)
from renamarr.radarr.models.movie_rename_plan import RadarrMovieRenamePlan


class MovieRename:
    """Service for renaming Radarr movie files."""

    def __init__(self, radarr_cli: RadarrCli, name: str = "") -> None:
        self.radarr_cli = radarr_cli
        self.name = name

    def process(self, movies: list[RadarrMovieItem]) -> None:
        """Rename movie files for movies with pending rename previews."""
        observability = get_observability()
        operation_result: OperationResult = OperationResult.FAILED
        with observability.start_span(
            "renamarr.radarr.rename",
            attributes={
                "service": ServiceName.RADARR,
                "name": self.name,
                "operation": OperationName.RENAME,
            },
        ):
            try:
                observability.record_operation_scanned_items(
                    ServiceName.RADARR,
                    self.name,
                    OperationName.RENAME,
                    len(movies),
                )
                movie_rename_plan = self.__build_movie_rename_plan(movies)
                movie_ids = movie_rename_plan.get_movie_ids()
                observability.record_operation_candidate_items(
                    ServiceName.RADARR,
                    self.name,
                    OperationName.RENAME,
                    len(movie_ids),
                )

                if not movie_rename_plan.has_movie_renames():
                    operation_result = OperationResult.NOOP
                    return

                movie_names = movie_rename_plan.get_movie_titles()
                logger.info(f"Renaming Movies: {movie_names}")
                try:
                    self.radarr_cli._sendCommand(
                        {
                            "name": "RenameMovie",
                            "movieIds": movie_ids,
                        }
                    )
                except Exception:
                    observability.record_operation_items(
                        ServiceName.RADARR,
                        self.name,
                        OperationName.RENAME,
                        OperationResult.FAILED,
                        len(movie_ids),
                    )
                    raise
                observability.record_operation_items(
                    ServiceName.RADARR,
                    self.name,
                    OperationName.RENAME,
                    OperationResult.ACCEPTED,
                    len(movie_ids),
                )
                operation_result = OperationResult.ACCEPTED
                logger.info(f"Movie rename successful for movies: {movie_names}")
            finally:
                observability.record_operation_run(
                    ServiceName.RADARR,
                    self.name,
                    OperationName.RENAME,
                    operation_result,
                )

    def __build_movie_rename_plan(
        self, movies: list[RadarrMovieItem]
    ) -> RadarrMovieRenamePlan:
        movie_rename_plan = RadarrMovieRenamePlan()

        for movie in movies:
            with logger.contextualize(item=movie.title):
                files_to_rename: json_data = self.radarr_cli.request_get(
                    path="/api/v3/rename",
                    url_params=dict(movieId=movie.id),
                )

                if len(files_to_rename) == 0:
                    logger.debug("Nothing to rename")
                else:
                    logger.debug("Found movie files to be renamed")
                    movie_rename_plan.add_movie(movie)

        return movie_rename_plan
