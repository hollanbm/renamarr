from loguru import logger
from pycliarr.api import SonarrCli

from renamarr.observability import get_observability
from renamarr.sonarr.services.analyze_files import AnalyzeFiles
from renamarr.sonarr.services.series_folder_rename import SeriesFolderRename
from renamarr.sonarr.services.series_rename import SeriesRename


class SonarrRenamarr:
    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        analyze_files: bool = False,
        rename_folders: bool = False,
    ) -> None:
        self.name = name
        self.sonarr_cli = SonarrCli(url, api_key)
        self.analyze_files = analyze_files
        self.rename_folders = rename_folders

    def scan(self) -> None:
        """Run the Sonarr Renamarr workflow."""
        observability = get_observability()
        with observability.start_span(
            "renamarr.sonarr.scan",
            attributes={"service": "sonarr", "name": self.name, "job": "renamarr"},
        ):
            with logger.contextualize(instance=self.name):
                logger.info("Starting Renamarr")

                if self.analyze_files:
                    with observability.start_span(
                        "renamarr.sonarr.analyze_files",
                        attributes={
                            "service": "sonarr",
                            "name": self.name,
                            "operation": "analyze_files",
                        },
                    ):
                        AnalyzeFiles(self.sonarr_cli).process()

                series = sorted(
                    self.sonarr_cli.get_serie(), key=lambda show: show.title
                )
                if len(series) == 0:
                    logger.error("Sonarr returned empty series list")
                    logger.info("Finished Renamarr")
                    return

                logger.debug("Retrieved series list")

                SeriesRename(self.sonarr_cli, name=self.name).process(series)

                if self.rename_folders:
                    SeriesFolderRename(self.sonarr_cli, name=self.name).process(series)

                logger.info("Finished Renamarr")
