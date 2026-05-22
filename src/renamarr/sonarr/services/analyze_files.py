from time import sleep

from loguru import logger
from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data


class AnalyzeFiles:
    """Service for refreshing Sonarr media info."""

    def __init__(self, sonarr_cli: SonarrCli) -> None:
        self.sonarr_cli = sonarr_cli

    def process(self) -> None:
        """Rescan Sonarr files when media-info analysis is enabled."""
        if not self.__analyze_files_enabled():
            logger.warning(
                "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
            )
            return

        logger.info("Initiated disk scan of library")
        if self.__analyze_files():
            logger.info("disk scan finished successfully")
        else:
            logger.info("disk scan failed")

    def __analyze_files(self) -> bool:
        rescan_command = self.sonarr_cli._sendCommand(
            {
                "name": "RescanSeries",
                "priority": "high",
            }
        )
        resp: json_data = {}

        while resp.get("status") != "completed":
            sleep(10)
            resp = self.sonarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"

    def __analyze_files_enabled(self) -> bool:
        """Return whether Sonarr's media management "Analyse files" setting is enabled."""
        mediamanagement: json_data = self.sonarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
