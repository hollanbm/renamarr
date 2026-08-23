from collections.abc import Sequence
from json import loads

from pydantic import Field
from sonarr import (
    ApiClient,
    CommandApi,
    CommandPriority,
    CommandResource,
    Configuration,
    MediaManagementConfigApi,
    RenameEpisodeApi,
    RenameEpisodeResource,
    RootFolderApi,
    SeriesApi,
    SeriesEditorApi,
    SeriesEditorResource,
    SeriesFolderApi,
)
from sonarr import CommandResult as SonarrCommandResult
from sonarr import CommandStatus as SonarrCommandStatus
from sonarr.rest import ApiException

from renamarr.adapter_helpers import translate_api_error
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


class _SonarrCommandResource(CommandResource):
    """Add command-specific fields omitted from Sonarr's OpenAPI schema."""

    series_ids: list[int] | None = Field(default=None, alias="seriesIds")
    series_id: int | None = Field(default=None, alias="seriesId")
    files: list[int] | None = None


def _required[Value](value: Value | None, message: str) -> Value:
    if value is None:
        raise TypeError(message)
    return value


def _command_id(response: CommandResource) -> int:
    return _required(response.id, "Expected a numeric command ID from Sonarr")


def _episode_label(preview: RenameEpisodeResource) -> str:
    season_number = _required(
        preview.season_number,
        "Expected a season number in Sonarr rename preview",
    )
    episode_numbers = _required(
        preview.episode_numbers,
        "Expected episode numbers in Sonarr rename preview",
    )
    return f"S{season_number:02d}E" + "-".join(
        f"{episode_number:02d}" for episode_number in episode_numbers
    )


class SonarrAdapter:
    """Normalize sonarr-py's generated client for the Renamarr engine."""

    def __init__(self, url: str, api_key: str) -> None:
        configuration = Configuration(
            host=url,
            api_key={"X-Api-Key": api_key},
        )
        self._client = ApiClient(configuration)
        self._series_api = SeriesApi(self._client)
        self._media_management_api = MediaManagementConfigApi(self._client)
        self._command_api = CommandApi(self._client)
        self._rename_api = RenameEpisodeApi(self._client)
        self._root_folder_api = RootFolderApi(self._client)
        self._series_folder_api = SeriesFolderApi(self._client)
        self._series_editor_api = SeriesEditorApi(self._client)

    def list_media_items(self) -> list[MediaItem]:
        """Return the series in the Sonarr library."""
        series = translate_api_error(
            "Sonarr",
            ApiException,
            "List",
            "series",
            self._series_api.list_series,
        )
        if not isinstance(series, list):
            raise TypeError("Expected a list of series from Sonarr")
        return [
            MediaItem(
                id=_required(show.id, "Expected a series ID from Sonarr"),
                title=_required(show.title, "Expected a series title from Sonarr"),
                path=_required(show.path, "Expected a series path from Sonarr"),
            )
            for show in series
        ]

    def is_media_analysis_enabled(self) -> bool:
        """Return whether Sonarr is configured to analyze media files."""
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "Read",
            "media-management settings",
            self._media_management_api.get_media_management_config,
        )
        return _required(
            response.enable_media_info,
            "Expected enableMediaInfo to be a boolean",
        )

    def start_media_analysis(self) -> int:
        """Start a full Sonarr series rescan and return its command ID."""
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "Start",
            "media analysis",
            lambda: self._command_api.create_command(
                _SonarrCommandResource(
                    name="RescanSeries",
                    priority=CommandPriority.HIGH,
                )
            ),
        )
        return _command_id(response)

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized state of a Sonarr command."""
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "Read",
            "command status",
            lambda: self._command_api.get_command_by_id(command_id),
        )
        return CommandStatus(
            completed=response.status is SonarrCommandStatus.COMPLETED,
            successful=response.result is SonarrCommandResult.SUCCESSFUL,
        )

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a candidate containing Sonarr's episode rename preview."""
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "Preview",
            f"file rename for {item.title}",
            lambda: self._rename_api.list_rename(series_id=item.id),
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of rename previews from Sonarr")
        if not response:
            return None
        return FileRenameCandidate(
            item=item,
            file_ids=tuple(
                _required(
                    preview.episode_file_id,
                    "Expected an episode file ID in Sonarr rename preview",
                )
                for preview in response
            ),
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
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "Start",
            "file rename",
            lambda: self._command_api.create_command(
                _SonarrCommandResource(
                    name="RenameFiles",
                    files=list(batch.file_ids),
                    series_id=batch.item_ids[0],
                )
            ),
        )
        return _command_id(response)

    def list_root_folders(self) -> list[str]:
        """Return configured Sonarr root-folder paths."""
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "List",
            "root folders",
            self._root_folder_api.list_root_folder,
        )
        if not isinstance(response, list):
            raise TypeError("Expected a list of root folders from Sonarr")
        return [
            _required(root.path, "Expected a root-folder path from Sonarr")
            for root in response
        ]

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name Sonarr expects for a series."""

        def get_folder_payload() -> bytes:
            response = (
                self._series_folder_api.get_series_folder_without_preload_content(
                    id=item.id
                )
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
            "Sonarr",
            ApiException,
            "Resolve",
            f"folder for {item.title}",
            get_folder_payload,
        )
        folder_response = loads(payload)
        if not isinstance(folder_response, dict):
            raise TypeError("Expected an object response from Sonarr")
        folder = folder_response.get("folder")
        if not isinstance(folder, str):
            raise TypeError("Expected a folder name from Sonarr")
        return folder

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move a batch of Sonarr series folders through the public API."""
        translate_api_error(
            "Sonarr",
            ApiException,
            "Move",
            "series folders",
            lambda: self._series_editor_api.put_series_editor(
                SeriesEditorResource(
                    root_folder_path=batch.root_folder_path,
                    series_ids=list(batch.item_ids),
                    move_files=batch.move_files,
                )
            ),
        )

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int:
        """Start a Sonarr rescan for series whose folders moved."""
        response = translate_api_error(
            "Sonarr",
            ApiException,
            "Start",
            "folder rescan",
            lambda: self._command_api.create_command(
                _SonarrCommandResource(
                    name="RescanSeries",
                    priority=CommandPriority.HIGH,
                    series_ids=list(batch.item_ids),
                )
            ),
        )
        return _command_id(response)
