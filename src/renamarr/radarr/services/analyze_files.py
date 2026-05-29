from time import sleep

from loguru import logger
from pycliarr.api import RadarrCli
from pycliarr.api.base_api import json_data


class AnalyzeFiles:
    """Service for refreshing Radarr media info."""

    def __init__(self, radarr_cli: RadarrCli) -> None:
        self.radarr_cli = radarr_cli

    def process(self) -> None:
        """Rescan Radarr files when media-info analysis is enabled."""
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
        rescan_command = self.radarr_cli._sendCommand(
            {
                "name": "RescanMovie",
                "priority": "high",
            }
        )
        resp: json_data = {}

        while resp.get("status") != "completed":
            sleep(10)
            resp = self.radarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"

    def __analyze_files_enabled(self) -> bool:
        """Return whether Radarr's media management "Analyse files" setting is enabled."""
        mediamanagement: json_data = self.radarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
