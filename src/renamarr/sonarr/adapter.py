from collections.abc import Callable, Sequence

from pycliarr.api import SonarrCli
from pycliarr.api.base_api import json_data, json_dict
from pycliarr.api.exceptions import CliArrError

from renamarr.exceptions import ArrOperationError
from renamarr.models import (
    CommandStatus,
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


def _translate_api_error[Result](
    operation: str, action: Callable[[], Result]
) -> Result:
    try:
        return action()
    except CliArrError as error:
        raise ArrOperationError(f"{operation} failed: {error}") from error


def _as_dict(response: json_data) -> json_dict:
    if not isinstance(response, dict):
        raise TypeError("Expected an object response from Sonarr")
    return response


def _command_id(response: json_data) -> int:
    command_id = _as_dict(response)["id"]
    if not isinstance(command_id, int):
        raise TypeError("Expected a numeric command ID from Sonarr")
    return command_id


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
        series = _translate_api_error("List Sonarr series", self._client.get_serie)
        if not isinstance(series, list):
            raise TypeError("Expected a list of series from Sonarr")
        return [
            MediaItem(id=show.id, title=show.title, path=show.path) for show in series
        ]

    def is_media_analysis_enabled(self) -> bool:
        """Return whether Sonarr is configured to analyze media files."""
        response = _translate_api_error(
            "Read Sonarr media-management settings",
            lambda: self._client.request_get(path="/api/v3/config/mediamanagement"),
        )
        enabled = _as_dict(response)["enableMediaInfo"]
        if not isinstance(enabled, bool):
            raise TypeError("Expected enableMediaInfo to be a boolean")
        return enabled

    def start_media_analysis(self) -> int:
        """Start a full Sonarr series rescan and return its command ID."""
        response = _translate_api_error(
            "Start Sonarr media analysis",
            lambda: self._client._sendCommand(
                {"name": "RescanSeries", "priority": "high"}
            ),
        )
        return _command_id(response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Sonarr command."""
        response = _as_dict(
            _translate_api_error(
                "Read Sonarr command status",
                lambda: self._client.get_command(cid=command_id),
            )
        )
        return CommandStatus(
            completed=response.get("status") == "completed",
            successful=response.get("result") == "successful",
        )

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a candidate containing Sonarr's episode rename preview."""
        response = _translate_api_error(
            f"Preview Sonarr file rename for {item.title}",
            lambda: self._client.request_get(
                path="/api/v3/rename", url_params={"seriesId": item.id}
            ),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Sonarr")
        if not response:
            return None
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(preview["episodeFileId"] for preview in response),
            description=(
                f"{item.title}: "
                + ", ".join(_episode_label(preview) for preview in response)
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
        response = _translate_api_error(
            "Start Sonarr file rename",
            lambda: self._client.rename_files(list(batch.file_ids), batch.item_ids[0]),
        )
        return _command_id(response)

    def list_root_folders(self) -> list[str]:
        """Return configured Sonarr root-folder paths."""
        response = _translate_api_error(
            "List Sonarr root folders", self._client.get_root_folder
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Sonarr")
        return [root_folder["path"] for root_folder in response]

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Sonarr expects for a series."""
        response = _translate_api_error(
            f"Resolve Sonarr folder for {item.title}",
            lambda: self._client.request_get(path=f"/api/v3/series/{item.id}/folder"),
        )
        folder = _as_dict(response)["folder"]
        if not isinstance(folder, str):
            raise TypeError("Expected a folder name from Sonarr")
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Sonarr series folders through the public API."""
        _translate_api_error(
            "Move Sonarr series folders",
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
        response = _translate_api_error(
            "Start Sonarr folder rescan",
            lambda: self._client._sendCommand(
                {
                    "name": "RescanSeries",
                    "priority": "high",
                    "seriesIds": [item.id for item in batch.items],
                }
            ),
        )
        return _command_id(response)
