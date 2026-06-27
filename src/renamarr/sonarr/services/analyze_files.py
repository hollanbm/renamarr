import time
from time import sleep

from loguru import logger
from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data

from renamarr.observability import ArrCommandResult, ServiceName, get_observability

MAX_WAIT_SECONDS = 5 * 60


class AnalyzeFiles:
    """Service for refreshing Sonarr media info."""

    def __init__(self, sonarr_cli: SonarrCli, name: str = "") -> None:
        self.sonarr_cli = sonarr_cli
        self.name = name

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
        observability = get_observability()
        command_name = "RescanSeries"
        start_time = time.time()
        result = ArrCommandResult.FAILED
        try:
            rescan_command = self.sonarr_cli._sendCommand(
                {
                    "name": command_name,
                    "priority": "high",
                }
            )
            resp: json_data = {}

            while resp.get("status") != "completed":
                if time.time() - start_time >= MAX_WAIT_SECONDS:
                    logger.error(
                        f"Timed out waiting for Sonarr analyze files command {rescan_command['id']} "
                        f"after {MAX_WAIT_SECONDS} seconds"
                    )
                    result = ArrCommandResult.TIMEOUT
                    return False
                sleep(10)
                resp = self.sonarr_cli.get_command(cid=rescan_command["id"])

            result = (
                ArrCommandResult.SUCCESSFUL
                if resp["result"] == ArrCommandResult.SUCCESSFUL
                else ArrCommandResult.FAILED
            )
            return result == ArrCommandResult.SUCCESSFUL
        finally:
            observability.record_arr_command(
                ServiceName.SONARR,
                self.name,
                command_name,
                result,
                time.time() - start_time,
            )

    def __analyze_files_enabled(self) -> bool:
        """Return whether Sonarr's media management "Analyse files" setting is enabled."""
        mediamanagement: json_data = self.sonarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
