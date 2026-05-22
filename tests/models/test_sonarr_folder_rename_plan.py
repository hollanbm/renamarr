from pycliarr.api import SonarrSerieItem

from renamarr.sonarr.models.folder_rename_plan import SonarrFolderRenamePlan


def make_series(series_id: int, title: str) -> SonarrSerieItem:
    return SonarrSerieItem(id=series_id, title=title)


def test_has_folder_renames_returns_false_when_empty() -> None:
    folder_rename_plan = SonarrFolderRenamePlan()

    assert folder_rename_plan.has_folder_renames() is False


def test_add_series_creates_root_folder_rename_and_reports_pending() -> None:
    folder_rename_plan = SonarrFolderRenamePlan()
    series = make_series(10, "Show")

    folder_rename_plan.add_series("/root", series)

    assert folder_rename_plan.has_folder_renames() is True
    assert len(folder_rename_plan.root_folder_renames) == 1
    root_folder_rename = folder_rename_plan.root_folder_renames[0]
    assert root_folder_rename.root_folder_path == "/root"
    assert root_folder_rename.series == [series]
    assert root_folder_rename.move_files is True


def test_add_series_appends_series_to_existing_root_folder_rename() -> None:
    folder_rename_plan = SonarrFolderRenamePlan()
    series_a = make_series(10, "Show A")
    series_b = make_series(20, "Show B")
    folder_rename_plan.add_series("/root", series_a)

    folder_rename_plan.add_series("/root", series_b)

    assert len(folder_rename_plan.root_folder_renames) == 1
    assert folder_rename_plan.root_folder_renames[0].series == [series_a, series_b]


def test_add_series_creates_new_root_folder_rename_when_root_differs() -> None:
    folder_rename_plan = SonarrFolderRenamePlan()
    series_a = make_series(10, "Show A")
    series_b = make_series(20, "Show B")
    folder_rename_plan.add_series("/root", series_a)

    folder_rename_plan.add_series("/other", series_b)

    assert len(folder_rename_plan.root_folder_renames) == 2
    assert folder_rename_plan.root_folder_renames[0].root_folder_path == "/root"
    assert folder_rename_plan.root_folder_renames[1].root_folder_path == "/other"


def test_get_series_ids_returns_root_folder_rename_series_ids() -> None:
    folder_rename_plan = SonarrFolderRenamePlan()
    folder_rename_plan.add_series("/root", make_series(10, "Show A"))
    folder_rename_plan.add_series("/root", make_series(20, "Show B"))

    assert folder_rename_plan.get_series_ids(
        folder_rename_plan.root_folder_renames[0]
    ) == [10, 20]


def test_get_series_titles_returns_root_folder_rename_series_titles() -> None:
    folder_rename_plan = SonarrFolderRenamePlan()
    folder_rename_plan.add_series("/root", make_series(10, "Show A"))
    folder_rename_plan.add_series("/root", make_series(20, "Show B"))

    assert (
        folder_rename_plan.get_series_titles(folder_rename_plan.root_folder_renames[0])
        == "Show A, Show B"
    )
