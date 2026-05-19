from dataclasses import dataclass

from pycliarr.api import SonarrSerieItem


@dataclass()
class SonarrMove:
    """
    Pending series editor operation, for renaming folders
    """

    rootFolderPath: str
    series: list[SonarrSerieItem]
    moveFiles: bool = True


class SonarrBulkMove:
    """Class maintains a list of pending SonarrMove operations"""

    def __init__(self):
        self.pending_moves: list[SonarrMove] = []

    def has_pending_moves(self) -> bool:
        return len(self.pending_moves) > 0

    def add(self, root_folder_path: str, series: SonarrSerieItem) -> None:
        """Create a new SonarrMove operation, or update an existing move."""
        for move in self.pending_moves:
            if root_folder_path == move.rootFolderPath:
                move.series.append(series)
                return

        self.pending_moves.append(SonarrMove(root_folder_path, [series]))

    def get_log_message(self, move: SonarrMove) -> str:
        """Return a comma-separated list of series titles for a pending move."""
        return ", ".join(series.title for series in move.series)

    def get_series_ids(self, move: SonarrMove) -> list[int]:
        """Return series IDs for the Sonarr series editor API payload."""
        return [series.id for series in move.series]
