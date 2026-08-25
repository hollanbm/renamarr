from dataclasses import dataclass
from enum import StrEnum


class ScanPhase(StrEnum):
    """A phase of the Renamarr workflow."""

    ANALYSIS = "analysis"
    DISCOVERY = "discovery"
    FILE_RENAMES = "file_renames"
    FOLDER_RENAMES = "folder_renames"


@dataclass(frozen=True, slots=True)
class WorkSummary:
    """Per-work-unit outcome counts for a workflow phase."""

    success: int = 0
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
