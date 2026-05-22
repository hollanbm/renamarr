from dataclasses import dataclass

from pycliarr.api import SonarrSerieItem


@dataclass()
class RootFolderRename:
    """Series to rename under a single Sonarr root folder."""

    root_folder_path: str
    series: list[SonarrSerieItem]
    move_files: bool = True


class SonarrFolderRenamePlan:
    """Plan for grouped Sonarr series folder rename operations."""

    def __init__(self) -> None:
        self.root_folder_renames: list[RootFolderRename] = []

    def has_folder_renames(self) -> bool:
        """Return whether any series folders need renames."""
        return len(self.root_folder_renames) > 0

    def add_series(self, root_folder_path: str, series: SonarrSerieItem) -> None:
        """Add a series to the folder rename group for its root folder."""
        for root_folder_rename in self.root_folder_renames:
            if root_folder_path == root_folder_rename.root_folder_path:
                root_folder_rename.series.append(series)
                return

        self.root_folder_renames.append(RootFolderRename(root_folder_path, [series]))

    def get_series_ids(self, root_folder_rename: RootFolderRename) -> list[int]:
        """Return series IDs for the Sonarr series editor API payload."""
        return [series.id for series in root_folder_rename.series]

    def get_series_titles(self, root_folder_rename: RootFolderRename) -> str:
        """Return a comma-separated list of series titles for a pending move."""
        return ", ".join(series.title for series in root_folder_rename.series)
