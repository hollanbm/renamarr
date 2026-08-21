from unittest.mock import MagicMock, call

import pytest
from pycliarr.api import SonarrSerieItem
from pycliarr.api.exceptions import CliArrError

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)
from renamarr.sonarr.adapter import SonarrAdapter


@pytest.fixture
def sonarr_client(mocker) -> MagicMock:
    return mocker.patch("renamarr.sonarr.adapter.SonarrCli").return_value


@pytest.fixture
def adapter(sonarr_client: MagicMock) -> SonarrAdapter:
    return SonarrAdapter("https://sonarr.test", "api-key")


def test_maps_series_to_shared_media_items(
    adapter: SonarrAdapter, sonarr_client: MagicMock
) -> None:
    sonarr_client.get_serie.return_value = [
        SonarrSerieItem(id=2, title="Show B", path="/tv/Show B"),
        SonarrSerieItem(id=1, title="Show A", path="/tv/Show A"),
    ]

    assert adapter.list_media_items() == [
        MediaItem(id=2, title="Show B", path="/tv/Show B"),
        MediaItem(id=1, title="Show A", path="/tv/Show A"),
    ]
    sonarr_client.get_serie.assert_called_once_with()


@pytest.mark.parametrize("enabled", [True, False])
def test_reads_media_analysis_setting(
    adapter: SonarrAdapter, sonarr_client: MagicMock, enabled: bool
) -> None:
    sonarr_client.request_get.return_value = {"enableMediaInfo": enabled}

    assert adapter.is_media_analysis_enabled() is enabled
    sonarr_client.request_get.assert_called_once_with(
        path="/api/v3/config/mediamanagement"
    )


def test_starts_media_analysis_and_maps_command_status(
    adapter: SonarrAdapter, sonarr_client: MagicMock
) -> None:
    sonarr_client._sendCommand.return_value = {"id": 17}
    sonarr_client.get_command.side_effect = [
        {"status": "started"},
        {"status": "completed", "result": "failed"},
        {"status": "completed", "result": "successful"},
    ]

    assert adapter.start_media_analysis() == 17
    assert adapter.get_command_status(17) == CommandStatus(False, False)
    assert adapter.get_command_status(17) == CommandStatus(True, False)
    assert adapter.get_command_status(17) == CommandStatus(True, True)
    sonarr_client._sendCommand.assert_called_once_with(
        {"name": "RescanSeries", "priority": "high"}
    )
    sonarr_client.get_command.assert_has_calls(
        [call(cid=17), call(cid=17), call(cid=17)]
    )


def test_maps_episode_previews_and_builds_one_batch_per_series(
    adapter: SonarrAdapter, sonarr_client: MagicMock
) -> None:
    show_a = MediaItem(1, "Show A", "/tv/Show A")
    show_b = MediaItem(2, "Show B", "/tv/Show B")
    sonarr_client.request_get.side_effect = [
        [],
        [
            {"episodeFileId": 10, "seasonNumber": 1, "episodeNumbers": [1]},
            {
                "episodeFileId": 20,
                "seasonNumber": 2,
                "episodeNumbers": [3, 4],
            },
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
    sonarr_client.request_get.assert_has_calls(
        [
            call(path="/api/v3/rename", url_params={"seriesId": 1}),
            call(path="/api/v3/rename", url_params={"seriesId": 1}),
        ]
    )


def test_starts_series_file_rename(
    adapter: SonarrAdapter, sonarr_client: MagicMock
) -> None:
    batch = FileRenameBatch((7,), (10, 20), "S01E01, S01E02")
    sonarr_client.rename_files.return_value = {"id": 23}

    assert adapter.start_file_rename(batch) == 23
    sonarr_client.rename_files.assert_called_once_with([10, 20], 7)


def test_uses_sonarr_folder_endpoints_and_payloads(
    adapter: SonarrAdapter, sonarr_client: MagicMock
) -> None:
    show_a = MediaItem(1, "Show A", "/tv/Old A")
    show_b = MediaItem(2, "Show B", "/tv/Old B")
    batch = FolderRenameBatch("/tv", (show_a, show_b), False)
    sonarr_client.get_root_folder.return_value = [
        {"path": "/tv"},
        {"path": "/tv-anime"},
    ]
    sonarr_client.request_get.return_value = {"folder": "Show A (2026)"}
    sonarr_client.request_put.return_value = {}
    sonarr_client._sendCommand.return_value = {"id": 29}

    assert adapter.list_root_folders() == ["/tv", "/tv-anime"]
    assert adapter.get_expected_folder_name(show_a) == "Show A (2026)"
    assert adapter.move_folder(batch) is None
    assert adapter.start_folder_rescan(batch) == 29
    sonarr_client.request_get.assert_called_once_with(path="/api/v3/series/1/folder")
    sonarr_client.request_put.assert_called_once_with(
        path="/api/v3/series/editor",
        json_data={
            "rootFolderPath": "/tv",
            "seriesIds": [1, 2],
            "moveFiles": False,
        },
    )
    sonarr_client._sendCommand.assert_called_once_with(
        {
            "name": "RescanSeries",
            "priority": "high",
            "seriesIds": [1, 2],
        }
    )


@pytest.mark.parametrize(
    ("boundary", "client_method"),
    [
        ("list", "get_serie"),
        ("setting", "request_get"),
        ("analysis", "_sendCommand"),
        ("status", "get_command"),
        ("preview", "request_get"),
        ("rename", "rename_files"),
        ("roots", "get_root_folder"),
        ("folder", "request_get"),
        ("move", "request_put"),
        ("rescan", "_sendCommand"),
    ],
)
def test_translates_cliarr_errors_at_every_api_boundary(
    adapter: SonarrAdapter,
    sonarr_client: MagicMock,
    boundary: str,
    client_method: str,
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
    getattr(sonarr_client, client_method).side_effect = CliArrError("broken")

    with pytest.raises(ArrOperationError, match="failed: broken") as error:
        operations[boundary]()

    assert isinstance(error.value.__cause__, CliArrError)


def test_does_not_translate_unexpected_errors(
    adapter: SonarrAdapter, sonarr_client: MagicMock
) -> None:
    sonarr_client.get_serie.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        adapter.list_media_items()


@pytest.mark.parametrize(
    ("operation", "response", "message"),
    [
        ("list", SonarrSerieItem(id=1), "Expected a list of series"),
        ("setting", [], "Expected an object response"),
        ("setting", {"enableMediaInfo": 1}, "Expected enableMediaInfo"),
        ("analysis", {"id": "1"}, "Expected a numeric command ID"),
        ("preview", {}, "Expected a list of rename previews"),
        ("roots", {}, "Expected a list of root folders"),
        ("folder", {"folder": 1}, "Expected a folder name"),
    ],
)
def test_rejects_malformed_sonarr_responses(
    adapter: SonarrAdapter,
    sonarr_client: MagicMock,
    operation: str,
    response: object,
    message: str,
) -> None:
    item = MediaItem(1, "Show", "/tv/Show")
    operations = {
        "list": (sonarr_client.get_serie, adapter.list_media_items),
        "setting": (
            sonarr_client.request_get,
            adapter.is_media_analysis_enabled,
        ),
        "analysis": (sonarr_client._sendCommand, adapter.start_media_analysis),
        "preview": (
            sonarr_client.request_get,
            lambda: adapter.get_file_rename_candidate(item),
        ),
        "roots": (sonarr_client.get_root_folder, adapter.list_root_folders),
        "folder": (
            sonarr_client.request_get,
            lambda: adapter.get_expected_folder_name(item),
        ),
    }
    client_call, adapter_call = operations[operation]
    client_call.return_value = response

    with pytest.raises(TypeError, match=message):
        adapter_call()
