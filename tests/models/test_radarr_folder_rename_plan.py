from pycliarr.api import RadarrMovieItem

from renamarr.radarr.models.folder_rename_plan import RadarrFolderRenamePlan


def test_has_folder_renames_returns_false_when_empty() -> None:
    folder_rename_plan = RadarrFolderRenamePlan()

    assert folder_rename_plan.has_folder_renames() is False


def test_add_movie_creates_root_folder_rename_and_reports_pending() -> None:
    folder_rename_plan = RadarrFolderRenamePlan()
    movie = RadarrMovieItem(id=10, title="Movie")

    folder_rename_plan.add_movie("/root", movie)

    assert folder_rename_plan.has_folder_renames() is True
    assert len(folder_rename_plan.root_folder_renames) == 1
    root_folder_rename = folder_rename_plan.root_folder_renames[0]
    assert root_folder_rename.root_folder_path == "/root"
    assert root_folder_rename.movies == [movie]
    assert root_folder_rename.move_files is True


def test_add_movie_appends_movie_to_existing_root_folder_rename() -> None:
    folder_rename_plan = RadarrFolderRenamePlan()
    movie_a = RadarrMovieItem(id=10, title="Movie A")
    movie_b = RadarrMovieItem(id=20, title="Movie B")
    folder_rename_plan.add_movie("/root", movie_a)

    folder_rename_plan.add_movie("/root", movie_b)

    assert len(folder_rename_plan.root_folder_renames) == 1
    assert folder_rename_plan.root_folder_renames[0].movies == [movie_a, movie_b]


def test_add_movie_creates_new_root_folder_rename_when_root_differs() -> None:
    folder_rename_plan = RadarrFolderRenamePlan()
    movie_a = RadarrMovieItem(id=1, title="Movie A")
    movie_b = RadarrMovieItem(id=2, title="Movie B")
    folder_rename_plan.add_movie("/root", movie_a)

    folder_rename_plan.add_movie("/other", movie_b)

    assert len(folder_rename_plan.root_folder_renames) == 2
    assert folder_rename_plan.root_folder_renames[0].root_folder_path == "/root"
    assert folder_rename_plan.root_folder_renames[1].root_folder_path == "/other"


def test_get_movie_ids_returns_root_folder_rename_movie_ids() -> None:
    folder_rename_plan = RadarrFolderRenamePlan()
    folder_rename_plan.add_movie("/root", RadarrMovieItem(id=10, title="Movie A"))
    folder_rename_plan.add_movie("/root", RadarrMovieItem(id=20, title="Movie B"))

    assert folder_rename_plan.get_movie_ids(
        folder_rename_plan.root_folder_renames[0]
    ) == [10, 20]


def test_get_movie_titles_returns_root_folder_rename_movie_titles() -> None:
    folder_rename_plan = RadarrFolderRenamePlan()
    folder_rename_plan.add_movie("/root", RadarrMovieItem(id=10, title="Movie A"))
    folder_rename_plan.add_movie("/root", RadarrMovieItem(id=20, title="Movie B"))

    assert (
        folder_rename_plan.get_movie_titles(folder_rename_plan.root_folder_renames[0])
        == "Movie A, Movie B"
    )
