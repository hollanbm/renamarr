from collections.abc import Sequence
from json import loads

from pydantic import Field
from radarr import (
    ApiClient,
    CommandApi,
    CommandPriority,
    CommandResource,
    Configuration,
    MediaManagementConfigApi,
    MovieApi,
    MovieEditorApi,
    MovieEditorResource,
    MovieFolderApi,
    RenameMovieApi,
    RootFolderApi,
)
from radarr import CommandResult as RadarrCommandResult
from radarr import CommandStatus as RadarrCommandStatus
from radarr.rest import ApiException

from renamarr.adapter_helpers import require, translate_api_error
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


class _RadarrCommandResource(CommandResource):
    """Add command-specific fields omitted from Radarr's OpenAPI schema."""

    movie_ids: list[int] | None = Field(default=None, alias="movieIds")


def _command_id(response: CommandResource) -> int:
    return require(response.id, "Expected a numeric command ID from Radarr")


class RadarrAdapter:
    """Normalize radarr-py's generated client for the Renamarr engine."""

    def __init__(self, url: str, api_key: str) -> None:
        configuration = Configuration(
            host=url,
            api_key={"X-Api-Key": api_key},
        )
        self._client = ApiClient(configuration)
        self._movie_api = MovieApi(self._client)
        self._media_management_api = MediaManagementConfigApi(self._client)
        self._command_api = CommandApi(self._client)
        self._rename_api = RenameMovieApi(self._client)
        self._root_folder_api = RootFolderApi(self._client)
        self._movie_folder_api = MovieFolderApi(self._client)
        self._movie_editor_api = MovieEditorApi(self._client)

    def close(self) -> None:
        """Release the generated client's HTTP connection pools."""
        self._client.rest_client.pool_manager.clear()

    def list_media_items(self) -> list[MediaItem]:
        """Return the movies in the Radarr library."""
        movies = translate_api_error(
            "Radarr",
            ApiException,
            "List",
            "movies",
            self._movie_api.list_movie,
        )
        if not isinstance(movies, list):
            raise TypeError("Expected a list of movies from Radarr")
        return [
            MediaItem(
                id=require(movie.id, "Expected a movie ID from Radarr"),
                title=require(movie.title, "Expected a movie title from Radarr"),
                path=require(movie.path, "Expected a movie path from Radarr"),
            )
            for movie in movies
        ]

    def is_media_analysis_enabled(self) -> bool:
        """Return whether Radarr is configured to analyze media files."""
        response = translate_api_error(
            "Radarr",
            ApiException,
            "Read",
            "media-management settings",
            self._media_management_api.get_media_management_config,
        )
        return require(
            response.enable_media_info,
            "Expected enableMediaInfo to be a boolean",
        )

    def start_media_analysis(self) -> int:
        """Start a full Radarr movie rescan and return its command ID."""
        response = translate_api_error(
            "Radarr",
            ApiException,
            "Start",
            "media analysis",
            lambda: self._command_api.create_command(
                _RadarrCommandResource(
                    name="RescanMovie",
                    priority=CommandPriority.HIGH,
                )
            ),
        )
        return _command_id(response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Radarr command."""
        response = translate_api_error(
            "Radarr",
            ApiException,
            "Read",
            "command status",
            lambda: self._command_api.get_command_by_id(command_id),
        )
        return CommandStatus(
            completed=response.status is RadarrCommandStatus.COMPLETED,
            successful=response.result is RadarrCommandResult.SUCCESSFUL,
        )

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a file-rename candidate when Radarr has a rename preview."""
        response = translate_api_error(
            "Radarr",
            ApiException,
            "Preview",
            f"file rename for {item.title}",
            lambda: self._rename_api.list_rename(movie_id=[item.id]),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Radarr")
        if not response:
            return None
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(
                require(
                    preview.movie_file_id,
                    "Expected a movie file ID in Radarr rename preview",
                )
                for preview in response
            ),
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
            ApiException,
            "Start",
            "file rename",
            lambda: self._command_api.create_command(
                _RadarrCommandResource(
                    name="RenameMovie",
                    movie_ids=list(batch.item_ids),
                )
            ),
        )
        return _command_id(response)

    def list_root_folders(self) -> list[str]:
        """Return configured Radarr root-folder paths."""
        response = translate_api_error(
            "Radarr",
            ApiException,
            "List",
            "root folders",
            self._root_folder_api.list_root_folder,
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Radarr")
        return [
            require(root.path, "Expected a root-folder path from Radarr")
            for root in response
        ]

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Radarr expects for a movie."""

        def get_folder_payload() -> bytes:
            response = self._movie_folder_api.get_movie_folder_without_preload_content(
                id=item.id
            )
            try:
                payload = response.read()
            finally:
                response.release_conn()
            if not 200 <= response.status <= 299:
                raise ApiException(
                    http_resp=response,
                    body=payload.decode("utf-8", errors="replace"),
                )
            return payload

        payload = translate_api_error(
            "Radarr",
            ApiException,
            "Resolve",
            f"folder for {item.title}",
            get_folder_payload,
        )
        folder_response = loads(payload)
        if not isinstance(folder_response, dict):
            raise TypeError("Expected an object response from Radarr")
        folder = folder_response.get("folder")
        if not isinstance(folder, str):
            raise TypeError("Expected a folder name from Radarr")
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Radarr movie folders through the public API."""
        translate_api_error(
            "Radarr",
            ApiException,
            "Move",
            "movie folders",
            lambda: self._movie_editor_api.put_movie_editor(
                MovieEditorResource(
                    root_folder_path=batch.root_folder_path,
                    movie_ids=list(batch.item_ids),
                    move_files=batch.move_files,
                )
            ),
        )

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int:
        """Start a Radarr refresh for movies whose folders moved."""
        response = translate_api_error(
            "Radarr",
            ApiException,
            "Start",
            "folder rescan",
            lambda: self._command_api.create_command(
                _RadarrCommandResource(
                    name="RefreshMovie",
                    priority=CommandPriority.HIGH,
                    movie_ids=list(batch.item_ids),
                )
            ),
        )
        return _command_id(response)
