import time
from time import sleep

from loguru import logger
from pycliarr.api import RadarrCli
from pycliarr.api.base_api import json_data

from renamarr.otel.arr_command_result import ArrCommandResult
from renamarr.otel.observability import get_observability
from renamarr.otel.service_name import ServiceName

MAX_WAIT_SECONDS = 5 * 60
POLL_INTERVAL_SECONDS = 2


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
        result = self.__analyze_files()
        if result is ArrCommandResult.SUCCESSFUL:
            logger.info("disk scan finished successfully")
        else:
            logger.info("disk scan failed")

    def __analyze_files(self) -> ArrCommandResult:
        observability = get_observability()
        command_name = "RescanMovie"
        start_time = time.monotonic()
        deadline = start_time + MAX_WAIT_SECONDS
        result = ArrCommandResult.FAILED
        try:
            rescan_command = self.radarr_cli._sendCommand(
                {
                    "name": command_name,
                    "priority": "high",
                }
            )

            while True:
                resp = self.radarr_cli.get_command(cid=rescan_command["id"])
                if resp.get("status") == "completed":
                    break

                remaining_wait_seconds = deadline - time.monotonic()
                if remaining_wait_seconds <= 0:
                    logger.error(
                        f"Timed out waiting for Radarr analyze files command {rescan_command['id']} "
                        f"after {MAX_WAIT_SECONDS} seconds"
                    )
                    result = ArrCommandResult.TIMEOUT
                    return result
                sleep(min(POLL_INTERVAL_SECONDS, remaining_wait_seconds))

            if resp["result"] == ArrCommandResult.SUCCESSFUL:
                result = ArrCommandResult.SUCCESSFUL
            else:
                result = ArrCommandResult.FAILED
            return result
        finally:
            observability.record_arr_command(
                ServiceName.RADARR,
                self.name,
                command_name,
                result,
                time.monotonic() - start_time,
            )

    def __analyze_files_enabled(self) -> bool:
        """Return whether Radarr's media management "Analyse files" setting is enabled."""
        mediamanagement: json_data = self.radarr_cli.request_get(
            path="/api/v3/config/mediamanagement"
        )

        return mediamanagement["enableMediaInfo"]
