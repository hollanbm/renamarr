from pycliarr.api import RadarrMovieItem


class RadarrMovieRenamePlan:
    """Plan for grouped Radarr movie file rename operations."""

    def __init__(self) -> None:
        self.movies: list[RadarrMovieItem] = []

    def has_movie_renames(self) -> bool:
        """Return whether any movies need file renames."""
        return len(self.movies) > 0

    def add_movie(self, movie: RadarrMovieItem) -> None:
        """Add a movie to the pending movie file rename operation."""
        self.movies.append(movie)

    def get_movie_ids(self) -> list[int]:
        """Return movie IDs for the Radarr RenameMovie command payload."""
        return [movie.id for movie in self.movies]

    def get_movie_titles(self) -> str:
        """Return a comma-separated list of movie titles for logging."""
        return ", ".join(movie.title for movie in self.movies)
