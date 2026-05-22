import time
from pathlib import PurePosixPath
from time import sleep

from loguru import logger
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data, json_dict

from renamarr.sonarr.models.folder_rename_plan import SonarrFolderRenamePlan

MAX_WAIT_SECONDS = 5 * 60


class SeriesRootFolderNotFoundError(Exception):
    """Raised when a Sonarr series path does not match any configured root folder."""


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
        sonarr_root_folders: list[json_dict] = sorted(
            self.sonarr_cli.get_root_folder(),
            key=lambda root_folder: root_folder["path"],
        )

        for show in series:
            with logger.contextualize(item=show.title):
                current_series_path = PurePosixPath(show.path)

                try:
                    series_root_folder = self.__find_series_root_folder(
                        current_series_path, sonarr_root_folders
                    )
                except SeriesRootFolderNotFoundError as error:
                    logger.error(str(error))
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
    ) -> json_dict:
        """Return the deepest Sonarr root folder matching the series path.

        PurePosixPath parent matching compares path parts, so sibling root folders
        with overlapping names like /tv and /tv-anime do not collide. When Sonarr
        has nested roots like /data/media and /data/media/tv, both can match the
        same series path; the deepest match preserves the series' actual root
        folder.

        Raises:
            SeriesRootFolderNotFoundError: If Sonarr has no root folder matching the
                series path.
        """

        # Nested root folders are a vaild radarr configuration
        # This makes it possible for a single series to match multiple root folders
        # collect all matches, so that we can select the best match, instead of the first match
        matching_root_folders: list[tuple[PurePosixPath, json_dict]] = []
        for root_folder in sonarr_root_folders:
            root_folder_path = PurePosixPath(root_folder["path"])

            if (
                root_folder_path == current_series_path
                or root_folder_path in current_series_path.parents
            ):
                matching_root_folders.append((root_folder_path, root_folder))

        if not matching_root_folders:
            raise SeriesRootFolderNotFoundError(
                f"Unable to determine matching Sonarr root folder for series path {current_series_path}"
            )

        return max(matching_root_folders, key=lambda match: len(match[0].parts))[1]

    def __rescan_series(self, series_ids: list[int]) -> bool:
        """Rescan the Sonarr series library after folder moves."""
        start = time.time()
        rescan_command = self.sonarr_cli._sendCommand(
            {"name": "RescanSeries", "priority": "high", "seriesIds": series_ids}
        )
        resp: json_data = {}

        while resp.get("status") != "completed":
            if time.time() - start >= MAX_WAIT_SECONDS:
                logger.error(
                    f"Timed out waiting for Sonarr series rescan command {rescan_command['id']} "
                    f"after {MAX_WAIT_SECONDS} seconds"
                )
                return False
            sleep(10)
            resp = self.sonarr_cli.get_command(cid=rescan_command["id"])

        return resp["result"] == "successful"
