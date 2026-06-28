import time
from time import sleep

from loguru import logger
from pycliarr.api import RadarrCli
from pycliarr.api.base_api import json_data

from renamarr.otel.arr_command_result import ArrCommandResult
from renamarr.otel.observability import get_observability
from renamarr.otel.service_name import ServiceName

MAX_WAIT_SECONDS = 5 * 60


class AnalyzeFiles:
    """Service for refreshing Radarr media info."""

    def __init__(self, radarr_cli: RadarrCli, name: str = "") -> None:
        self.radarr_cli = radarr_cli
        self.name = name

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
        observability = get_observability()
        command_name = "RescanMovie"
        start_time = time.time()
        result = ArrCommandResult.FAILED
        try:
            rescan_command = self.radarr_cli._sendCommand(
                {
                    "name": command_name,
                    "priority": "high",
                }
            )
            resp: json_data = {}

            while resp.get("status") != "completed":
                if time.time() - start_time >= MAX_WAIT_SECONDS:
                    logger.error(
                        f"Timed out waiting for Radarr analyze files command {rescan_command['id']} "
                        f"after {MAX_WAIT_SECONDS} seconds"
                    )
                    result = ArrCommandResult.TIMEOUT
                    return False
                sleep(10)
                resp = self.radarr_cli.get_command(cid=rescan_command["id"])

            result = (
                ArrCommandResult.SUCCESSFUL
                if resp["result"] == ArrCommandResult.SUCCESSFUL
                else ArrCommandResult.FAILED
            )
            return result == ArrCommandResult.SUCCESSFUL
        finally:
            observability.record_arr_command(
                ServiceName.RADARR,
                self.name,
                command_name,
                result,
                time.time() - start_time,
            )

    def __analyze_files_enabled(self) -> bool:
        """Return whether Radarr's media management "Analyse files" setting is enabled."""
        mediamanagement: json_data = self.radarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
