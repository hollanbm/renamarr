from dataclasses import dataclass

from pycliarr.api import RadarrMovieItem


@dataclass()
class RootFolderRename:
    """Movies to rename under a single Radarr root folder."""

    root_folder_path: str
    movies: list[RadarrMovieItem]
    move_files: bool = True


class RadarrFolderRenamePlan:
    """Plan for grouped Radarr movie folder rename operations."""

    def __init__(self) -> None:
        self.root_folder_renames: list[RootFolderRename] = []

    def has_folder_renames(self) -> bool:
        return len(self.root_folder_renames) > 0

    def add_movie(self, root_folder_path: str, movie: RadarrMovieItem) -> None:
        """Add a movie to the folder rename group for its root folder."""
        for root_folder_rename in self.root_folder_renames:
            if root_folder_path == root_folder_rename.root_folder_path:
                root_folder_rename.movies.append(movie)
                return

        self.root_folder_renames.append(RootFolderRename(root_folder_path, [movie]))

    def get_movie_ids(self, root_folder_rename: RootFolderRename) -> list[int]:
        """Return movie IDs for the Radarr movie editor API payload."""
        return [movie.id for movie in root_folder_rename.movies]

    def get_movie_titles(self, root_folder_rename: RootFolderRename) -> str:
        """Return a comma-separated list of movie titles for a pending move."""
        return ", ".join(movie.title for movie in root_folder_rename.movies)
