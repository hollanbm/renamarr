from unittest.mock import MagicMock, call

import pytest
from pytest_mock import MockerFixture
from sonarr import (
    CommandResource,
    MediaManagementConfigResource,
    RenameEpisodeResource,
    RootFolderResource,
    SeriesEditorResource,
    SeriesResource,
)
from sonarr import CommandResult as SonarrCommandResult
from sonarr import CommandStatus as SonarrCommandStatus
from sonarr.rest import ApiException

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)
from renamarr.sonarr.sonarr_adapter import SonarrAdapter


@pytest.fixture
def sonarr_apis(mocker: MockerFixture) -> dict[str, MagicMock]:
    mocker.patch("renamarr.sonarr.sonarr_adapter.ApiClient")
    return {
        name: mocker.patch(f"renamarr.sonarr.sonarr_adapter.{name}").return_value
        for name in (
            "SeriesApi",
            "MediaManagementConfigApi",
            "CommandApi",
            "RenameEpisodeApi",
            "RootFolderApi",
            "SeriesFolderApi",
            "SeriesEditorApi",
        )
    }


@pytest.fixture
def adapter(sonarr_apis: dict[str, MagicMock]) -> SonarrAdapter:
    return SonarrAdapter("https://sonarr.test", "api-key")


def test_maps_series_to_shared_media_items(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    series_api = sonarr_apis["SeriesApi"]
    series_api.list_series.return_value = [
        SeriesResource(id=2, title="Show B", path="/tv/Show B"),
        SeriesResource(id=1, title="Show A", path="/tv/Show A"),
    ]

    assert adapter.list_media_items() == [
        MediaItem(id=2, title="Show B", path="/tv/Show B"),
        MediaItem(id=1, title="Show A", path="/tv/Show A"),
    ]
    series_api.list_series.assert_called_once_with()


@pytest.mark.parametrize("enabled", [True, False])
def test_reads_media_analysis_setting(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    enabled: bool,
) -> None:
    media_management_api = sonarr_apis["MediaManagementConfigApi"]
    media_management_api.get_media_management_config.return_value = (
        MediaManagementConfigResource(enable_media_info=enabled)
    )

    assert adapter.is_media_analysis_enabled() is enabled
    media_management_api.get_media_management_config.assert_called_once_with()


def test_starts_media_analysis_and_maps_command_status(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    command_api = sonarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=17)
    command_api.get_command_by_id.side_effect = [
        CommandResource(status=SonarrCommandStatus.STARTED),
        CommandResource(
            status=SonarrCommandStatus.COMPLETED,
            result=SonarrCommandResult.UNSUCCESSFUL,
        ),
        CommandResource(
            status=SonarrCommandStatus.COMPLETED,
            result=SonarrCommandResult.SUCCESSFUL,
        ),
    ]

    assert adapter.start_media_analysis() == 17
    assert adapter.get_command_status(17) == CommandStatus(False, False)
    assert adapter.get_command_status(17) == CommandStatus(True, False)
    assert adapter.get_command_status(17) == CommandStatus(True, True)
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RescanSeries",
        "priority": "high",
    }
    command_api.get_command_by_id.assert_has_calls([call(17), call(17), call(17)])


def test_maps_episode_previews_and_builds_one_batch_per_series(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    show_a = MediaItem(1, "Show A", "/tv/Show A")
    show_b = MediaItem(2, "Show B", "/tv/Show B")
    rename_api = sonarr_apis["RenameEpisodeApi"]
    rename_api.list_rename.side_effect = [
        [],
        [
            RenameEpisodeResource(
                episode_file_id=10,
                season_number=1,
                episode_numbers=[1],
            ),
            RenameEpisodeResource(
                episode_file_id=20,
                season_number=2,
                episode_numbers=[3, 4],
            ),
        ],
    ]

    assert adapter.get_file_rename_candidate(show_a) is None
    candidate_a = adapter.get_file_rename_candidate(show_a)
    assert candidate_a == FileRenameCandidate(
        show_a, (10, 20), "Show A: S01E01, S02E03-04"
    )
    candidate_b = FileRenameCandidate(show_b, (30,), "Show B: S03E05")
    assert adapter.build_file_rename_batches((candidate_a, candidate_b)) == [
        FileRenameBatch((1,), (10, 20), "Show A: S01E01, S02E03-04"),
        FileRenameBatch((2,), (30,), "Show B: S03E05"),
    ]
    assert adapter.build_file_rename_batches(()) == []
    rename_api.list_rename.assert_has_calls([call(series_id=1), call(series_id=1)])


def test_starts_series_file_rename(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    batch = FileRenameBatch((7,), (10, 20), "S01E01, S01E02")
    command_api = sonarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=23)

    assert adapter.start_file_rename(batch) == 23
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RenameFiles",
        "files": [10, 20],
        "seriesId": 7,
    }


def test_uses_sonarr_folder_endpoints_and_payloads(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    show_a = MediaItem(1, "Show A", "/tv/Old A")
    show_b = MediaItem(2, "Show B", "/tv/Old B")
    batch = FolderRenameBatch("/tv", (show_a, show_b), False)
    root_folder_api = sonarr_apis["RootFolderApi"]
    root_folder_api.list_root_folder.return_value = [
        RootFolderResource(path="/tv"),
        RootFolderResource(path="/tv-anime"),
    ]
    series_folder_api = sonarr_apis["SeriesFolderApi"]
    folder_response = MagicMock(status=200)
    folder_response.read.return_value = b'{"folder": "Show A (2026)"}'
    series_folder_api.get_series_folder_without_preload_content.return_value = (
        folder_response
    )
    command_api = sonarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=29)

    assert adapter.list_root_folders() == ["/tv", "/tv-anime"]
    assert adapter.get_expected_folder_name(show_a) == "Show A (2026)"
    assert adapter.move_folder(batch) is None
    assert adapter.start_folder_rescan(batch) == 29
    series_folder_api.get_series_folder_without_preload_content.assert_called_once_with(
        id=1
    )
    folder_response.read.assert_called_once_with()
    folder_response.release_conn.assert_called_once_with()
    series_editor_api = sonarr_apis["SeriesEditorApi"]
    editor = series_editor_api.put_series_editor.call_args.args[0]
    assert isinstance(editor, SeriesEditorResource)
    assert editor.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "seriesIds": [1, 2],
        "rootFolderPath": "/tv",
        "moveFiles": False,
    }
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RescanSeries",
        "priority": "high",
        "seriesIds": [1, 2],
    }


@pytest.mark.parametrize(
    ("boundary", "api_name", "method_name"),
    [
        ("list", "SeriesApi", "list_series"),
        ("setting", "MediaManagementConfigApi", "get_media_management_config"),
        ("analysis", "CommandApi", "create_command"),
        ("status", "CommandApi", "get_command_by_id"),
        ("preview", "RenameEpisodeApi", "list_rename"),
        ("rename", "CommandApi", "create_command"),
        ("roots", "RootFolderApi", "list_root_folder"),
        (
            "folder",
            "SeriesFolderApi",
            "get_series_folder_without_preload_content",
        ),
        ("move", "SeriesEditorApi", "put_series_editor"),
        ("rescan", "CommandApi", "create_command"),
    ],
)
def test_translates_api_errors_at_every_boundary(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    boundary: str,
    api_name: str,
    method_name: str,
) -> None:
    item = MediaItem(1, "Show", "/tv/Show")
    file_batch = FileRenameBatch((1,), (10,), "S01E01")
    folder_batch = FolderRenameBatch("/tv", (item,))
    operations = {
        "list": adapter.list_media_items,
        "setting": adapter.is_media_analysis_enabled,
        "analysis": adapter.start_media_analysis,
        "status": lambda: adapter.get_command_status(1),
        "preview": lambda: adapter.get_file_rename_candidate(item),
        "rename": lambda: adapter.start_file_rename(file_batch),
        "roots": adapter.list_root_folders,
        "folder": lambda: adapter.get_expected_folder_name(item),
        "move": lambda: adapter.move_folder(folder_batch),
        "rescan": lambda: adapter.start_folder_rescan(folder_batch),
    }
    getattr(sonarr_apis[api_name], method_name).side_effect = ApiException(
        reason="broken"
    )

    with pytest.raises(ArrOperationError, match="failed:") as error:
        operations[boundary]()

    assert isinstance(error.value.__cause__, ApiException)
    assert "broken" in str(error.value)


def test_does_not_translate_unexpected_errors(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    sonarr_apis["SeriesApi"].list_series.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        adapter.list_media_items()


@pytest.mark.parametrize(
    ("operation", "response", "message"),
    [
        ("list", SeriesResource(id=1), "Expected a list of series"),
        (
            "setting",
            MediaManagementConfigResource(),
            "Expected enableMediaInfo",
        ),
        ("analysis", CommandResource(), "Expected a numeric command ID"),
        ("preview", {}, "Expected a list of rename previews"),
        ("roots", {}, "Expected a list of root folders"),
    ],
)
def test_rejects_malformed_top_level_responses(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    operation: str,
    response: object,
    message: str,
) -> None:
    item = MediaItem(1, "Show", "/tv/Show")
    operations = {
        "list": (sonarr_apis["SeriesApi"].list_series, adapter.list_media_items),
        "setting": (
            sonarr_apis["MediaManagementConfigApi"].get_media_management_config,
            adapter.is_media_analysis_enabled,
        ),
        "analysis": (
            sonarr_apis["CommandApi"].create_command,
            adapter.start_media_analysis,
        ),
        "preview": (
            sonarr_apis["RenameEpisodeApi"].list_rename,
            lambda: adapter.get_file_rename_candidate(item),
        ),
        "roots": (
            sonarr_apis["RootFolderApi"].list_root_folder,
            adapter.list_root_folders,
        ),
    }
    client_call, adapter_call = operations[operation]
    client_call.return_value = response

    with pytest.raises(TypeError, match=message):
        adapter_call()


@pytest.mark.parametrize(
    ("series", "message"),
    [
        (SeriesResource(title="Show", path="/tv/Show"), "Expected a series ID"),
        (SeriesResource(id=1, path="/tv/Show"), "Expected a series title"),
        (SeriesResource(id=1, title="Show"), "Expected a series path"),
    ],
)
def test_rejects_series_missing_required_fields(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    series: SeriesResource,
    message: str,
) -> None:
    sonarr_apis["SeriesApi"].list_series.return_value = [series]

    with pytest.raises(TypeError, match=message):
        adapter.list_media_items()


@pytest.mark.parametrize(
    ("preview", "message"),
    [
        (
            RenameEpisodeResource(season_number=1, episode_numbers=[1]),
            "Expected an episode file ID",
        ),
        (
            RenameEpisodeResource(episode_file_id=10, episode_numbers=[1]),
            "Expected a season number",
        ),
        (
            RenameEpisodeResource(episode_file_id=10, season_number=1),
            "Expected episode numbers",
        ),
    ],
)
def test_rejects_rename_preview_missing_required_fields(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    preview: RenameEpisodeResource,
    message: str,
) -> None:
    sonarr_apis["RenameEpisodeApi"].list_rename.return_value = [preview]

    with pytest.raises(TypeError, match=message):
        adapter.get_file_rename_candidate(MediaItem(1, "Show", "/tv/Show"))


def test_rejects_root_folder_missing_path(
    adapter: SonarrAdapter, sonarr_apis: dict[str, MagicMock]
) -> None:
    sonarr_apis["RootFolderApi"].list_root_folder.return_value = [RootFolderResource()]

    with pytest.raises(TypeError, match="Expected a root-folder path"):
        adapter.list_root_folders()


@pytest.mark.parametrize("status", [199, 300])
def test_rejects_non_successful_folder_response_before_parsing(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    status: int,
) -> None:
    folder_response = MagicMock(status=status, reason="Unexpected status")
    folder_response.read.return_value = b"not json"
    sonarr_apis[
        "SeriesFolderApi"
    ].get_series_folder_without_preload_content.return_value = folder_response

    with pytest.raises(
        ArrOperationError, match="Resolve Sonarr folder.*failed"
    ) as error:
        adapter.get_expected_folder_name(MediaItem(1, "Show", "/tv/Show"))

    assert isinstance(error.value.__cause__, ApiException)
    assert error.value.__cause__.status == status
    assert error.value.__cause__.body == "not json"
    folder_response.release_conn.assert_called_once_with()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"[]", "Expected an object response"),
        (b'{"folder": 1}', "Expected a folder name"),
    ],
)
def test_rejects_malformed_folder_response(
    adapter: SonarrAdapter,
    sonarr_apis: dict[str, MagicMock],
    payload: bytes,
    message: str,
) -> None:
    folder_response = MagicMock(status=200)
    folder_response.read.return_value = payload
    sonarr_apis[
        "SeriesFolderApi"
    ].get_series_folder_without_preload_content.return_value = folder_response

    with pytest.raises(TypeError, match=message):
        adapter.get_expected_folder_name(MediaItem(1, "Show", "/tv/Show"))

    folder_response.release_conn.assert_called_once_with()
