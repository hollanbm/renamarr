from collections.abc import Sequence
from pathlib import PurePosixPath

from lidarr import (
    ApiClient,
    ArtistApi,
    ArtistEditorApi,
    ArtistEditorResource,
    ArtistLookupApi,
    ArtistResource,
    CommandApi,
    CommandPriority,
    CommandResource,
    Configuration,
    RenameTrackApi,
    RootFolderApi,
)
from lidarr import CommandResult as LidarrCommandResult
from lidarr import CommandStatus as LidarrCommandStatus
from lidarr.rest import ApiException
from pydantic import Field

from renamarr.adapter_helpers import require, translate_api_error
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


class _LidarrCommandResource(CommandResource):
    """Add command-specific fields omitted from Lidarr's OpenAPI schema."""

    artist_id: int | None = Field(default=None, alias="artistId")
    artist_ids: list[int] | None = Field(default=None, alias="artistIds")
    files: list[int] | None = None
    folders: list[str] | None = None
    filter: str | None = None
    add_new_artists: bool | None = Field(default=None, alias="addNewArtists")


def _command_id(response: CommandResource) -> int:
    return require(response.id, "Expected a numeric command ID from Lidarr")


class LidarrAdapter:
    """Normalize lidarr-py's generated client for the Renamarr engine."""

    def __init__(self, url: str, api_key: str) -> None:
        configuration = Configuration(
            host=url,
            api_key={"X-Api-Key": api_key},
        )
        self._client = ApiClient(configuration)
        self._artist_api = ArtistApi(self._client)
        self._artist_lookup_api = ArtistLookupApi(self._client)
        self._command_api = CommandApi(self._client)
        self._rename_api = RenameTrackApi(self._client)
        self._root_folder_api = RootFolderApi(self._client)
        self._artist_editor_api = ArtistEditorApi(self._client)
        self._artists: dict[int, ArtistResource] = {}
        self._expected_folders: dict[int, str] = {}

    def close(self) -> None:
        """Release the generated client's HTTP connection pools."""
        self._client.rest_client.pool_manager.clear()

    def list_media_items(self) -> list[MediaItem]:
        """Return the artists in the Lidarr library."""
        artists = translate_api_error(
            "Lidarr",
            ApiException,
            "List",
            "artists",
            self._artist_api.list_artist,
        )
        if not isinstance(artists, list):
            raise TypeError("Expected a list of artists from Lidarr")

        items: list[MediaItem] = []
        for artist in artists:
            artist_id = require(artist.id, "Expected an artist ID from Lidarr")
            self._artists[artist_id] = artist
            items.append(
                MediaItem(
                    id=artist_id,
                    title=require(
                        artist.artist_name,
                        "Expected an artist name from Lidarr",
                    ),
                    path=require(artist.path, "Expected an artist path from Lidarr"),
                )
            )
        return items

    def is_media_analysis_enabled(self) -> bool:
        """Return True because Lidarr always supports direct folder rescans."""
        return True

    def start_media_analysis(self) -> int:
        """Start a full Lidarr folder rescan and return its command ID."""
        response = translate_api_error(
            "Lidarr",
            ApiException,
            "Start",
            "media analysis",
            lambda: self._command_api.create_command(
                _LidarrCommandResource(
                    name="RescanFolders",
                    priority=CommandPriority.HIGH,
                    filter="known",
                    add_new_artists=False,
                )
            ),
        )
        return _command_id(response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Lidarr command."""
        response = translate_api_error(
            "Lidarr",
            ApiException,
            "Read",
            "command status",
            lambda: self._command_api.get_command_by_id(command_id),
        )
        return CommandStatus(
            completed=response.status is LidarrCommandStatus.COMPLETED,
            successful=response.result is LidarrCommandResult.SUCCESSFUL,
        )

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a candidate containing Lidarr's track rename preview."""
        response = translate_api_error(
            "Lidarr",
            ApiException,
            "Preview",
            f"file rename for {item.title}",
            lambda: self._rename_api.list_rename(artist_id=item.id),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Lidarr")
        if not response:
            return None
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(
                require(
                    preview.track_file_id,
                    "Expected a track file ID in Lidarr rename preview",
                )
                for preview in response
            ),
            description=item.title,
        )

    def build_file_rename_batches(
        self, candidates: Sequence[FileRenameCandidate]
    ) -> list[FileRenameBatch]:
        """Build one Lidarr RenameFiles batch per artist."""
        return [
            FileRenameBatch(
                item_ids=(candidate.item.id,),
                file_ids=candidate.file_ids,
                description=candidate.description,
            )
            for candidate in candidates
        ]

    def start_file_rename(self, batch: FileRenameBatch) -> int:
        """Start a Lidarr RenameFiles command for one artist."""
        response = translate_api_error(
            "Lidarr",
            ApiException,
            "Start",
            "file rename",
            lambda: self._command_api.create_command(
                _LidarrCommandResource(
                    name="RenameFiles",
                    artist_id=batch.item_ids[0],
                    files=list(batch.file_ids),
                )
            ),
        )
        return _command_id(response)

    def list_root_folders(self) -> list[str]:
        """Return configured Lidarr root-folder paths."""
        response = translate_api_error(
            "Lidarr",
            ApiException,
            "List",
            "root folders",
            self._root_folder_api.list_root_folder,
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Lidarr")
        return [
            require(root.path, "Expected a root-folder path from Lidarr")
            for root in response
        ]

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Lidarr expects for an artist."""
        cached_folder = self._expected_folders.get(item.id)
        if cached_folder is not None:
            return cached_folder

        artist = self._artists.get(item.id)
        if artist is None:
            artist = translate_api_error(
                "Lidarr",
                ApiException,
                "Read",
                f"artist {item.title}",
                lambda: self._artist_api.get_artist_by_id(item.id),
            )
            self._artists[item.id] = artist

        foreign_artist_id = require(
            artist.foreign_artist_id,
            "Expected a foreign artist ID from Lidarr",
        )
        lookup_results = translate_api_error(
            "Lidarr",
            ApiException,
            "Resolve",
            f"folder for {item.title}",
            lambda: self._artist_lookup_api.list_artist_lookup(
                term=f"lidarr:{foreign_artist_id}"
            ),
        )
        if not isinstance(lookup_results, list):
            raise TypeError("Expected a list of artist lookup results from Lidarr")
        matching_artist = require(
            next(
                (
                    lookup_artist
                    for lookup_artist in lookup_results
                    if lookup_artist.foreign_artist_id == foreign_artist_id
                ),
                None,
            ),
            "Expected an exact artist lookup result from Lidarr",
        )
        folder = require(
            matching_artist.folder,
            "Expected an artist folder from Lidarr",
        )
        self._expected_folders[item.id] = folder
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Lidarr artist folders through the public API."""
        translate_api_error(
            "Lidarr",
            ApiException,
            "Move",
            "artist folders",
            lambda: self._artist_editor_api.put_artist_editor(
                ArtistEditorResource(
                    root_folder_path=batch.root_folder_path,
                    artist_ids=list(batch.item_ids),
                    move_files=batch.move_files,
                )
            ),
        )

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int:
        """Start a Lidarr rescan for artists whose folders moved."""
        folders = [
            str(
                PurePosixPath(batch.root_folder_path)
                / self.get_expected_folder_name(item)
            )
            for item in batch.items
        ]
        response = translate_api_error(
            "Lidarr",
            ApiException,
            "Start",
            "folder rescan",
            lambda: self._command_api.create_command(
                _LidarrCommandResource(
                    name="RescanFolders",
                    priority=CommandPriority.HIGH,
                    artist_ids=list(batch.item_ids),
                    folders=folders,
                    filter="known",
                    add_new_artists=False,
                )
            ),
        )
        return _command_id(response)
