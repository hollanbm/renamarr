from pycliarr.api import RadarrMovieItem

from renamarr.radarr.models.movie_rename_plan import RadarrMovieRenamePlan


def test_has_movie_renames_returns_false_when_empty() -> None:
    movie_rename_plan = RadarrMovieRenamePlan()

    assert movie_rename_plan.has_movie_renames() is False


def test_add_movie_stores_movie_and_reports_pending() -> None:
    movie_rename_plan = RadarrMovieRenamePlan()
    movie = RadarrMovieItem(id=10, title="Movie")

    movie_rename_plan.add_movie(movie)

    assert movie_rename_plan.has_movie_renames() is True
    assert movie_rename_plan.movies == [movie]


def test_get_movie_ids_returns_pending_movie_ids() -> None:
    movie_rename_plan = RadarrMovieRenamePlan()
    movie_rename_plan.add_movie(RadarrMovieItem(id=10, title="Movie A"))
    movie_rename_plan.add_movie(RadarrMovieItem(id=20, title="Movie B"))

    assert movie_rename_plan.get_movie_ids() == [10, 20]


def test_get_movie_titles_returns_pending_movie_titles() -> None:
    movie_rename_plan = RadarrMovieRenamePlan()
    movie_rename_plan.add_movie(RadarrMovieItem(id=10, title="Movie A"))
    movie_rename_plan.add_movie(RadarrMovieItem(id=20, title="Movie B"))

    assert movie_rename_plan.get_movie_titles() == "Movie A, Movie B"
