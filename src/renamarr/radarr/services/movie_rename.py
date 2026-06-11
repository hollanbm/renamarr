from loguru import logger
from pycliarr.api import RadarrCli, RadarrMovieItem
from pycliarr.api.base_api import json_data

from renamarr.observability import get_observability
from renamarr.radarr.models.movie_rename_plan import RadarrMovieRenamePlan


class MovieRename:
    """Service for renaming Radarr movie files."""

    def __init__(self, radarr_cli: RadarrCli, name: str = "") -> None:
        self.radarr_cli = radarr_cli
        self.name = name

    def process(self, movies: list[RadarrMovieItem]) -> None:
        """Rename movie files for movies with pending rename previews."""
        observability = get_observability()
        with observability.start_span(
            "renamarr.radarr.rename",
            attributes={
                "service": "radarr",
                "name": self.name,
                "operation": "rename",
            },
        ):
            movie_rename_plan = self.__build_movie_rename_plan(movies)

            if not movie_rename_plan.has_movie_renames():
                return

            movie_names = movie_rename_plan.get_movie_titles()
            movie_ids = movie_rename_plan.get_movie_ids()
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
                    "radarr",
                    "rename",
                    self.name,
                    "failed",
                    len(movie_ids),
                )
                raise
            observability.record_operation_items(
                "radarr",
                "rename",
                self.name,
                "accepted",
                len(movie_ids),
            )
            logger.info(f"Movie rename successful for movies: {movie_names}")

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
