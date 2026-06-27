from loguru import logger
from pycliarr.api import RadarrCli

from renamarr.observability import get_observability
from renamarr.radarr.services.analyze_files import AnalyzeFiles
from renamarr.radarr.services.movie_folder_rename import MovieFolderRename
from renamarr.radarr.services.movie_rename import MovieRename


class RadarrRenamarr:
    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        analyze_files: bool = False,
        rename_folders: bool = False,
    ) -> None:
        self.name = name
        self.radarr_cli = RadarrCli(url, api_key)
        self.analyze_files = analyze_files
        self.rename_folders = rename_folders

    def scan(self) -> None:
        """Run the Radarr Renamarr workflow."""
        observability = get_observability()
        with observability.start_span(
            "renamarr.radarr.scan",
            attributes={"service": "radarr", "name": self.name, "job": "renamarr"},
        ):
            with logger.contextualize(instance=self.name):
                logger.info("Starting Renamarr")

                if self.analyze_files:
                    with observability.start_span(
                        "renamarr.radarr.analyze_files",
                        attributes={
                            "service": "radarr",
                            "name": self.name,
                            "operation": "analyze_files",
                        },
                    ):
                        AnalyzeFiles(self.radarr_cli, name=self.name).process()

                movies = sorted(
                    self.radarr_cli.get_movie(), key=lambda movie: movie.title
                )
                if len(movies) == 0:
                    logger.error("Radarr returned empty movie list")
                    logger.info("Finished Renamarr")
                    return

                logger.debug("Retrieved movie list")

                MovieRename(self.radarr_cli, name=self.name).process(movies)

                if self.rename_folders:
                    MovieFolderRename(self.radarr_cli, name=self.name).process(movies)

                logger.info("Finished Renamarr")
