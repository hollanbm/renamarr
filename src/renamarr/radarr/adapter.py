from collections.abc import Callable, Sequence

from pycliarr.api import RadarrCli
from pycliarr.api.base_api import json_data, json_dict
from pycliarr.api.exceptions import CliArrError

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
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
        raise TypeError("Expected an object response from Radarr")
    return response


def _command_id(response: json_data) -> int:
    command_id = _as_dict(response)["id"]
    if not isinstance(command_id, int):
        raise TypeError("Expected a numeric command ID from Radarr")
    return command_id


class RadarrAdapter:
    """Normalize pycliarr's Radarr client for the shared Renamarr engine."""

    def __init__(self, url: str, api_key: str) -> None:
        self._client = RadarrCli(url, api_key)

    def list_media_items(self) -> list[MediaItem]:
        """Return the movies in the Radarr library."""
        movies = _translate_api_error("List Radarr movies", self._client.get_movie)
        if not isinstance(movies, list):
            raise TypeError("Expected a list of movies from Radarr")
        return [
            MediaItem(id=movie.id, title=movie.title, path=movie.path)
            for movie in movies
        ]

    def is_media_analysis_enabled(self) -> bool:
        """Return whether Radarr is configured to analyze media files."""
        response = _translate_api_error(
            "Read Radarr media-management settings",
            lambda: self._client.request_get(path="/api/v3/config/mediamanagement"),
        )
        enabled = _as_dict(response)["enableMediaInfo"]
        if not isinstance(enabled, bool):
            raise TypeError("Expected enableMediaInfo to be a boolean")
        return enabled

    def start_media_analysis(self) -> int:
        """Start a full Radarr movie rescan and return its command ID."""
        response = _translate_api_error(
            "Start Radarr media analysis",
            lambda: self._client._sendCommand(
                {"name": "RescanMovie", "priority": "high"}
            ),
        )
        return _command_id(response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Radarr command."""
        response = _as_dict(
            _translate_api_error(
                "Read Radarr command status",
                lambda: self._client.get_command(cid=command_id),
            )
        )
        return CommandStatus(
            completed=response.get("status") == "completed",
            successful=response.get("result") == "successful",
        )

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a file-rename candidate when Radarr has a rename preview."""
        response = _translate_api_error(
            f"Preview Radarr file rename for {item.title}",
            lambda: self._client.request_get(
                path="/api/v3/rename", url_params={"movieId": item.id}
            ),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Radarr")
        if not response:
            return None
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(preview["movieFileId"] for preview in response),
            description=item.title,
        )

    def build_file_rename_batches(
        self, candidates: Sequence[FileRenameCandidate]
    ) -> list[FileRenameBatch]:
        """Combine Radarr rename candidates into one RenameMovie batch."""
        if not candidates:
            return []
        return [
            FileRenameBatch(
                item_ids=tuple(candidate.item.id for candidate in candidates),
                file_ids=tuple(
                    file_id
                    for candidate in candidates
                    for file_id in candidate.file_ids
                ),
                description=", ".join(
                    candidate.description for candidate in candidates
                ),
            )
        ]

    def start_file_rename(self, batch: FileRenameBatch) -> int:
        """Start a Radarr RenameMovie command for a batch."""
        response = _translate_api_error(
            "Start Radarr file rename",
            lambda: self._client._sendCommand(
                {"name": "RenameMovie", "movieIds": list(batch.item_ids)}
            ),
        )
        return _command_id(response)

    def list_root_folders(self) -> list[str]:
        """Return configured Radarr root-folder paths."""
        response = _translate_api_error(
            "List Radarr root folders", self._client.get_root_folder
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Radarr")
        return [root_folder["path"] for root_folder in response]

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Radarr expects for a movie."""
        response = _translate_api_error(
            f"Resolve Radarr folder for {item.title}",
            lambda: self._client.request_get(path=f"/api/v3/movie/{item.id}/folder"),
        )
        folder = _as_dict(response)["folder"]
        if not isinstance(folder, str):
            raise TypeError("Expected a folder name from Radarr")
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Radarr movie folders through the public API."""
        _translate_api_error(
            "Move Radarr movie folders",
            lambda: self._client.request_put(
                path="/api/v3/movie/editor",
                json_data={
                    "rootFolderPath": batch.root_folder_path,
                    "movieIds": [item.id for item in batch.items],
                    "moveFiles": batch.move_files,
                },
            ),
        )

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int:
        """Start a Radarr refresh for movies whose folders moved."""
        response = _translate_api_error(
            "Start Radarr folder rescan",
            lambda: self._client._sendCommand(
                {
                    "priority": "high",
                    "name": "RefreshMovie",
                    "movieIds": [item.id for item in batch.items],
                }
            ),
        )
        return _command_id(response)
