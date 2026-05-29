from renamarr.sonarr.models.episode_rename_plan import SonarrEpisodeRenamePlan


def test_has_episode_renames_returns_false_when_empty() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()

    assert episode_rename_plan.has_episode_renames() is False


def test_add_episode_file_stores_episode_and_reports_pending() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()

    episode_rename_plan.add_episode_file(
        file_id=10,
        season_number=1,
        episode_numbers=[2],
    )

    assert episode_rename_plan.has_episode_renames() is True
    assert len(episode_rename_plan.files_to_rename) == 1
    episode_rename = episode_rename_plan.files_to_rename[0]
    assert episode_rename.file_id == 10
    assert episode_rename.season_number == 1
    assert episode_rename.episode_numbers == [2]


def test_get_file_ids_returns_pending_episode_file_ids() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()
    episode_rename_plan.add_episode_file(10, 1, [1])
    episode_rename_plan.add_episode_file(20, 1, [2])

    assert episode_rename_plan.get_file_ids() == [10, 20]


def test_get_log_message_returns_single_episode_label() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()
    episode_rename_plan.add_episode_file(10, 1, [1])

    assert episode_rename_plan.get_log_message() == "S01E01"


def test_get_log_message_returns_multiple_episode_labels() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()
    episode_rename_plan.add_episode_file(10, 1, [1])
    episode_rename_plan.add_episode_file(20, 1, [2])

    assert episode_rename_plan.get_log_message() == "S01E01, S01E02"


def test_get_log_message_returns_multi_episode_file_label() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()
    episode_rename_plan.add_episode_file(10, 1, [1, 2])

    assert episode_rename_plan.get_log_message() == "S01E01-02"


def test_get_log_message_returns_mixed_episode_labels() -> None:
    episode_rename_plan = SonarrEpisodeRenamePlan()
    episode_rename_plan.add_episode_file(10, 1, [1])
    episode_rename_plan.add_episode_file(20, 1, [2, 3])

    assert episode_rename_plan.get_log_message() == "S01E01, S01E02-03"
