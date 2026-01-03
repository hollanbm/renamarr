from typing import List

from models.move import Move


class BulkMove:
    """Class maintains a list of pending Move operations"""

    def __init__(self):
        self.pending_moves: List[Move] = []

    def has_pending_moves(self) -> bool:
        return len(self.pending_moves) > 0

    def add(self, root_folder_path: str, series_id: int) -> None:
        """_summary_

        Creates a new Move operation, or updates an existing move

        Args:
            root_folder_path (str): root_folder_path
            series_id (int): series_id

        Returns:
            _type_: None
        """
        # Update existing operation
        for move in self.pending_moves:
            if root_folder_path == move.rootFolderPath:
                move.seriesIds.append(series_id)
                return

        # Operation doesn't exist, create it
        self.pending_moves.append(Move(root_folder_path, [series_id]))
        return

    def get_log_message(self) -> str:
        series_list: List[str] = []
        for move in self.pending_moves:
            series_list.append(move.seriesIds)

        series_list2: List[int] = [
            (str(move.series_ids)) for move in self.pending_moves
        ]
        return ", ".join(series_list2)
