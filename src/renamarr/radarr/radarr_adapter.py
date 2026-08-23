from collections.abc import Sequence

from pycliarr.api import RadarrCli
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


class RadarrAdapter:
    """Normalize pycliarr's Radarr client for the shared Renamarr engine."""

    def __init__(self, url: str, api_key: str) -> None:
        self._client = RadarrCli(url, api_key)

    def list_media_items(self) -> list[MediaItem]:
        """Return the movies in the Radarr library."""
        movies = translate_api_error(
            "Radarr", CliArrError, "List", "movies", self._client.get_movie
        )
        if not isinstance(movies, list):
            raise TypeError("Expected a list of movies from Radarr")
        return [
            MediaItem(id=movie.id, title=movie.title, path=movie.path)
            for movie in movies
        ]

    def is_media_analysis_enabled(self) -> bool:
        """Return whether Radarr is configured to analyze media files."""
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "Read",
            "media-management settings",
            lambda: self._client.request_get(path="/api/v3/config/mediamanagement"),
        )
        enabled = as_dict("Radarr", response).get("enableMediaInfo")
        if not isinstance(enabled, bool):
            raise TypeError("Expected enableMediaInfo to be a boolean")
        return enabled

    def start_media_analysis(self) -> int:
        """Start a full Radarr movie rescan and return its command ID."""
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "Start",
            "media analysis",
            lambda: send_command(
                self._client, {"name": "RescanMovie", "priority": "high"}
            ),
        )
        return command_id("Radarr", response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Radarr command."""
        response = as_dict(
            "Radarr",
            translate_api_error(
                "Radarr",
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
        """Return a file-rename candidate when Radarr has a rename preview."""
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "Preview",
            f"file rename for {item.title}",
            lambda: self._client.request_get(
                path="/api/v3/rename", url_params={"movieId": item.id}
            ),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Radarr")
        if not response:
            return None
        file_ids: list[int] = []
        for preview in response:
            preview_dict = as_dict("Radarr", preview)
            movie_file_id = preview_dict.get("movieFileId")
            if type(movie_file_id) is not int:
                raise TypeError("Expected a movie file ID in Radarr rename preview")
            file_ids.append(movie_file_id)
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(file_ids),
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
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "Start",
            "file rename",
            lambda: send_command(
                self._client,
                {"name": "RenameMovie", "movieIds": list(batch.item_ids)},
            ),
        )
        return command_id("Radarr", response)

    def list_root_folders(self) -> list[str]:
        """Return configured Radarr root-folder paths."""
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "List",
            "root folders",
            self._client.get_root_folder,
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Radarr")
        paths: list[str] = []
        for root_folder in response:
            path = as_dict("Radarr", root_folder).get("path")
            if not isinstance(path, str):
                raise TypeError("Expected a root-folder path from Radarr")
            paths.append(path)
        return paths

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Radarr expects for a movie."""
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "Resolve",
            f"folder for {item.title}",
            lambda: self._client.request_get(path=f"/api/v3/movie/{item.id}/folder"),
        )
        folder = as_dict("Radarr", response).get("folder")
        if not isinstance(folder, str):
            raise TypeError("Expected a folder name from Radarr")
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Radarr movie folders through the public API."""
        translate_api_error(
            "Radarr",
            CliArrError,
            "Move",
            "movie folders",
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
        response = translate_api_error(
            "Radarr",
            CliArrError,
            "Start",
            "folder rescan",
            lambda: send_command(
                self._client,
                {
                    "priority": "high",
                    "name": "RefreshMovie",
                    "movieIds": [item.id for item in batch.items],
                },
            ),
        )
        return command_id("Radarr", response)
