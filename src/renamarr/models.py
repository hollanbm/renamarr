from dataclasses import dataclass
from enum import StrEnum


class ScanPhase(StrEnum):
    """A phase of the Renamarr workflow."""

    ANALYSIS = "analysis"
    DISCOVERY = "discovery"
    FILE_RENAMES = "file_renames"
    FOLDER_RENAMES = "folder_renames"


@dataclass(frozen=True, slots=True)
class MediaItem:
    """A media item managed by an Arr service."""

    id: int
    title: str
    path: str


@dataclass(frozen=True, slots=True)
class FileRenameCandidate:
    """An item whose files need to be renamed."""

    item: MediaItem
    file_ids: tuple[int, ...]
    description: str


@dataclass(frozen=True, slots=True)
class FileRenameBatch:
    """A file rename operation that can be submitted as one command."""

    item_ids: tuple[int, ...]
    file_ids: tuple[int, ...]
    description: str


@dataclass(frozen=True, slots=True)
class FolderRenameBatch:
    """Media folders that can be moved together under one root folder."""

    root_folder_path: str
    items: tuple[MediaItem, ...]
    move_files: bool = True

    @property
    def item_ids(self) -> tuple[int, ...]:
        """Return the IDs of the items in this batch."""
        return tuple(item.id for item in self.items)

    @property
    def titles(self) -> tuple[str, ...]:
        """Return the titles of the items in this batch."""
        return tuple(item.title for item in self.items)


@dataclass(frozen=True, slots=True)
class CommandStatus:
    """The normalized state of an Arr command."""

    completed: bool
    successful: bool


@dataclass(frozen=True, slots=True)
class WorkSummary:
    """Per-work-unit outcome counts for a workflow phase."""

    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass(frozen=True, slots=True)
class ScanFailure:
    """An expected failure encountered during a scan."""

    phase: ScanPhase
    item_ids: tuple[int, ...]
    message: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The structured result of a Renamarr scan."""

    items_found: int
    analysis: WorkSummary
    file_renames: WorkSummary
    folder_renames: WorkSummary
    failures: tuple[ScanFailure, ...]

    @property
    def successful(self) -> bool:
        """Return whether the scan completed without failed work."""
        return (
            self.items_found > 0
            and not self.failures
            and self.analysis.failed == 0
            and self.file_renames.failed == 0
            and self.folder_renames.failed == 0
        )


@dataclass(frozen=True, slots=True)
class CommandPollingSettings:
    """Settings for polling asynchronous Arr commands for completion."""

    timeout_seconds: int = 120
    check_interval_seconds: int = 3

    def __post_init__(self) -> None:
        if type(self.timeout_seconds) is not int or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        if (
            type(self.check_interval_seconds) is not int
            or self.check_interval_seconds <= 0
        ):
            raise ValueError("check_interval_seconds must be a positive integer")
        if self.check_interval_seconds > self.timeout_seconds:
            raise ValueError("check_interval_seconds must not exceed timeout_seconds")
