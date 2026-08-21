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

    def list_media_items(self) -> list[MediaItem]: ...

    def is_media_analysis_enabled(self) -> bool: ...

    def start_media_analysis(self) -> int: ...

    def get_command_status(self, command_id: int) -> CommandStatus: ...

    def get_file_rename_candidate(
        self, item: MediaItem
    ) -> FileRenameCandidate | None: ...

    def build_file_rename_batches(
        self, candidates: Sequence[FileRenameCandidate]
    ) -> list[FileRenameBatch]: ...

    def start_file_rename(self, batch: FileRenameBatch) -> int: ...

    def list_root_folders(self) -> list[str]: ...

    def get_expected_folder_name(self, item: MediaItem) -> str: ...

    def move_folder(self, batch: FolderRenameBatch) -> None: ...

    def start_folder_rescan(self, batch: FolderRenameBatch) -> int: ...
