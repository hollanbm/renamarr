from dataclasses import dataclass


@dataclass()
class RadarrMove:
    """
    JSON payload for movie editor endpoint, for renaming folders
    """

    rootFolderPath: str
    movieIds: list[int]
    moveFiles: bool = True


class RadarrBulkMove:
    """Class maintains a list of pending RadarrMove operations"""

    def __init__(self):
        self.pending_moves: list[RadarrMove] = []

    def has_pending_moves(self) -> bool:
        return len(self.pending_moves) > 0

    def add(self, root_folder_path: str, movie_id: int) -> None:
        """Create a new RadarrMove operation, or update an existing move."""
        for move in self.pending_moves:
            if root_folder_path == move.rootFolderPath:
                move.movieIds.append(movie_id)
                return

        self.pending_moves.append(RadarrMove(root_folder_path, [movie_id]))
