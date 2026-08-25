from collections.abc import Sequence
from typing import Protocol

from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


class ArrAdapter(Protocol):
    """Normalized operations required by the shared Renamarr workflow."""

    def close(self) -> None:
        """Release resources owned by the service client."""
        ...

    def list_media_items(self) -> list[MediaItem]:
        """Return all media items from the configured service."""
        ...

    def is_media_analysis_enabled(self) -> bool:
        """Return whether the service analyzes media files."""
        ...

    def start_media_analysis(self) -> int:
        """Start media analysis and return its command ID."""
        ...

    def get_command_status(self, command_id: int) -> CommandStatus:
        """Return the normalized status of a submitted command."""
        ...

    def get_file_rename_candidate(self, item: MediaItem) -> FileRenameCandidate | None:
        """Return a rename candidate, or None when no rename is needed."""
        ...

    def build_file_rename_batches(
        self, candidates: Sequence[FileRenameCandidate]
    ) -> list[FileRenameBatch]:
        """Group candidates into service-specific rename batches."""
        ...

    def start_file_rename(self, batch: FileRenameBatch) -> int:
        """Start a file rename and return its command ID."""
        ...

    def list_root_folders(self) -> list[str]:
        """Return the configured root-folder paths."""
        ...

    def get_expected_folder_name(self, item: MediaItem) -> str:
        """Return the folder name expected for a media item."""
        ...

    def move_folder(self, batch: FolderRenameBatch) -> None:
        """Move the folders described by a rename batch."""
        ...

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int:
        """Start a rescan after folder moves and return its command ID."""
        ...
