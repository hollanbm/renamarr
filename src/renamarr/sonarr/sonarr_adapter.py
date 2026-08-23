from collections.abc import Sequence

from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_dict
from pycliarr.api.exceptions import CliArrError

from renamarr.adapter_helpers import (
    as_dict,
    command_id,
    send_command,
    translate_api_error,
)
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


def _episode_label(preview: json_dict) -> str:
    season_number = preview["seasonNumber"]
    episode_numbers = preview["episodeNumbers"]
    return f"S{season_number:02d}E" + "-".join(
        f"{episode_number:02d}" for episode_number in episode_numbers
    )


class SonarrAdapter:
    """Normalize pycliarr's Sonarr client for the shared Renamarr engine."""

    def __init__(self, url: str, api_key: str) -> None:
        self._client = SonarrCli(url, api_key)

    def list_media_items(self) -> list[MediaItem]:
        """Return the series in the Sonarr library."""
        series = translate_api_error(
            "Sonarr", CliArrError, "List", "series", self._client.get_serie
        )
        if not isinstance(series, list):
            raise TypeError("Expected a list of series from Sonarr")
        return [
            MediaItem(id=show.id, title=show.title, path=show.path) for show in series
        ]

    def is_media_analysis_enabled(self) -> bool:
        """Return whether Sonarr is configured to analyze media files."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "Read",
            "media-management settings",
            lambda: self._client.request_get(path="/api/v3/config/mediamanagement"),
        )
        enabled = as_dict("Sonarr", response).get("enableMediaInfo")
        if not isinstance(enabled, bool):
            raise TypeError("Expected enableMediaInfo to be a boolean")
        return enabled

    def start_media_analysis(self) -> int:
        """Start a full Sonarr series rescan and return its command ID."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "Start",
            "media analysis",
            lambda: send_command(
                self._client, {"name": "RescanSeries", "priority": "high"}
            ),
        )
        return command_id("Sonarr", response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Sonarr command."""
        response = as_dict(
            "Sonarr",
            translate_api_error(
                "Sonarr",
                CliArrError,
                "Read",
                "command status",
                lambda: self._client.get_command(cid=command_id),
            ),
        )
        return CommandStatus(
            completed=response.get("status") == "completed",
            successful=response.get("result") == "successful",
        )

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a candidate containing Sonarr's episode rename preview."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "Preview",
            f"file rename for {item.title}",
            lambda: self._client.request_get(
                path="/api/v3/rename", url_params={"seriesId": item.id}
            ),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Sonarr")
        if not response:
            return None
        file_ids: list[int] = []
        previews: list[json_dict] = []
        for preview in response:
            preview_dict = as_dict("Sonarr", preview)
            episode_file_id = preview_dict.get("episodeFileId")
            if type(episode_file_id) is not int:
                raise TypeError("Expected an episode file ID in Sonarr rename preview")
            season_number = preview_dict.get("seasonNumber")
            if type(season_number) is not int:
                raise TypeError("Expected a season number in Sonarr rename preview")
            episode_numbers = preview_dict.get("episodeNumbers")
            if not isinstance(episode_numbers, list):
                raise TypeError(
                    "Expected episode numbers in Sonarr rename preview to be a list"
                )
            if any(
                type(episode_number) is not int for episode_number in episode_numbers
            ):
                raise TypeError(
                    "Expected integer episode numbers in Sonarr rename preview"
                )
            file_ids.append(episode_file_id)
            previews.append(preview_dict)
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(file_ids),
            description=(
                f"{item.title}: "
                + ", ".join(_episode_label(preview) for preview in previews)
            ),
        )

    def build_file_rename_batches(
        self, candidates: Sequence[FileRenameCandidate]
    ) -> list[FileRenameBatch]:
        """Build one Sonarr RenameFiles batch per series."""
        return [
            FileRenameBatch(
                item_ids=(candidate.item.id,),
                file_ids=candidate.file_ids,
                description=candidate.description,
            )
            for candidate in candidates
        ]

    def start_file_rename(self, batch: FileRenameBatch) -> int:
        """Start a Sonarr RenameFiles command for one series."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "Start",
            "file rename",
            lambda: self._client.rename_files(list(batch.file_ids), batch.item_ids[0]),
        )
        return command_id("Sonarr", response)

    def list_root_folders(self) -> list[str]:
        """Return configured Sonarr root-folder paths."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "List",
            "root folders",
            self._client.get_root_folder,
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Sonarr")
        paths: list[str] = []
        for root_folder in response:
            path = as_dict("Sonarr", root_folder).get("path")
            if not isinstance(path, str):
                raise TypeError("Expected a root-folder path from Sonarr")
            paths.append(path)
        return paths

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Sonarr expects for a series."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "Resolve",
            f"folder for {item.title}",
            lambda: self._client.request_get(path=f"/api/v3/series/{item.id}/folder"),
        )
        folder = as_dict("Sonarr", response).get("folder")
        if not isinstance(folder, str):
            raise TypeError("Expected a folder name from Sonarr")
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Sonarr series folders through the public API."""
        translate_api_error(
            "Sonarr",
            CliArrError,
            "Move",
            "series folders",
            lambda: self._client.request_put(
                path="/api/v3/series/editor",
                json_data={
                    "rootFolderPath": batch.root_folder_path,
                    "seriesIds": [item.id for item in batch.items],
                    "moveFiles": batch.move_files,
                },
            ),
        )

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int:
        """Start a Sonarr rescan for series whose folders moved."""
        response = translate_api_error(
            "Sonarr",
            CliArrError,
            "Start",
            "folder rescan",
            lambda: send_command(
                self._client,
                {
                    "name": "RescanSeries",
                    "priority": "high",
                    "seriesIds": [item.id for item in batch.items],
                },
            ),
        )
        return command_id("Sonarr", response)
