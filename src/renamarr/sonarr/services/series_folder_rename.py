from pathlib import PurePosixPath
from time import sleep

from loguru import logger
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data, json_dict

from renamarr.sonarr.models.folder_rename_plan import SonarrFolderRenamePlan


class SeriesFolderRename:
    """Service for renaming Sonarr series folders."""

    def __init__(self, sonarr_cli: SonarrCli) -> None:
        self.sonarr_cli = sonarr_cli

    def process(self, series: list[SonarrSerieItem]) -> None:
        """Rename series folders whose path differs from Sonarr's expected folder."""
        folder_rename_plan = self.__build_folder_rename_plan(series)

        if not folder_rename_plan.has_folder_renames():
            return

        logger.debug("Processing pending series folder renames")
        for root_folder_rename in folder_rename_plan.root_folder_renames:
            series_titles = folder_rename_plan.get_series_titles(root_folder_rename)
            series_ids = folder_rename_plan.get_series_ids(root_folder_rename)

            multiple_series = len(series_ids) > 1
            logger.info(
                f"Renaming Series {'folders' if multiple_series else 'folder'} "
                f"for: {series_titles}"
            )
            folder_rename_response = self.sonarr_cli.request_put(
                path="/api/v3/series/editor",
                json_data=dict(
                    rootFolderPath=root_folder_rename.root_folder_path,
                    seriesIds=series_ids,
                    moveFiles=root_folder_rename.move_files,
                ),
            )
            if not 200 <= folder_rename_response.status_code <= 299:
                logger.error(
                    f"Series folder rename failed for series: {series_titles}: "
                    f"status code {folder_rename_response.status_code}"
                )
                continue

            logger.info(f"Series folder rename successful for series: {series_titles}")
            logger.info("Initiated disk scan of updated series")
            if self.__rescan_series(series_ids):
                logger.info("disk scan finished successfully")
            else:
                logger.info("disk scan failed")

    def __build_folder_rename_plan(
        self, series: list[SonarrSerieItem]
    ) -> SonarrFolderRenamePlan:
        folder_rename_plan = SonarrFolderRenamePlan()
        sonarr_root_folders: list[json_dict] = self.sonarr_cli.get_root_folder()

        for show in series:
            with logger.contextualize(item=show.title):
                current_series_path = PurePosixPath(show.path)
                series_root_folder = self.__find_series_root_folder(
                    current_series_path, sonarr_root_folders
                )

                if series_root_folder is None:
                    logger.warning(
                        f"Unable to determine matching Sonarr root folder for series path {current_series_path}"
                    )
                    continue

                expected_folder_name: str = self.sonarr_cli.request_get(
                    path=f"/api/v3/series/{show.id}/folder"
                )["folder"]
                series_root_folder_path = series_root_folder["path"]
                expected_series_folder_path = (
                    PurePosixPath(series_root_folder_path) / expected_folder_name
                )

                if expected_series_folder_path != current_series_path:
                    folder_rename_plan.add_series(series_root_folder_path, show)
                    logger.debug("added series to pending folder_rename_plan operation")

        return folder_rename_plan

    def __find_series_root_folder(
        self,
        current_series_path: PurePosixPath,
        sonarr_root_folders: list[json_dict],
    ) -> json_dict | None:
        """Return the Sonarr root folder whose path is a parent of the series path."""
        for root_folder in sonarr_root_folders:
            root_folder_path = PurePosixPath(root_folder["path"])

            if root_folder_path in current_series_path.parents:
                return root_folder

        return None

    def __rescan_series(self, series_ids: list[int]) -> bool:
        """Rescan the Sonarr series library after folder moves."""
        rescan_command = self.sonarr_cli._sendCommand(
            {"name": "RescanSeries", "priority": "high", "seriesIds": series_ids}
        )
        resp: json_data = {}

        while resp.get("status") != "completed":
            sleep(10)
            resp = self.sonarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"
