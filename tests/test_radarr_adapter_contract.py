from unittest.mock import MagicMock, call

import pytest
from pycliarr.api import RadarrMovieItem
from pycliarr.api.exceptions import CliArrError

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)
from renamarr.radarr.radarr_adapter import RadarrAdapter


@pytest.fixture
def radarr_client(mocker) -> MagicMock:
    client = mocker.patch("renamarr.radarr.radarr_adapter.RadarrCli").return_value
    client.api_url_command = "/api/v3/command"
    return client


@pytest.fixture
def adapter(radarr_client: MagicMock) -> RadarrAdapter:
    return RadarrAdapter("https://radarr.test", "api-key")


def test_maps_movies_to_shared_media_items(
    adapter: RadarrAdapter, radarr_client: MagicMock
) -> None:
    radarr_client.get_movie.return_value = [
        RadarrMovieItem(id=2, title="Movie B", path="/movies/Movie B"),
        RadarrMovieItem(id=1, title="Movie A", path="/movies/Movie A"),
    ]

    assert adapter.list_media_items() == [
        MediaItem(id=2, title="Movie B", path="/movies/Movie B"),
        MediaItem(id=1, title="Movie A", path="/movies/Movie A"),
    ]
    radarr_client.get_movie.assert_called_once_with()


@pytest.mark.parametrize("enabled", [True, False])
def test_reads_media_analysis_setting(
    adapter: RadarrAdapter, radarr_client: MagicMock, enabled: bool
) -> None:
    radarr_client.request_get.return_value = {"enableMediaInfo": enabled}

    assert adapter.is_media_analysis_enabled() is enabled
    radarr_client.request_get.assert_called_once_with(
        path="/api/v3/config/mediamanagement"
    )


def test_starts_media_analysis_and_maps_command_status(
    adapter: RadarrAdapter, radarr_client: MagicMock
) -> None:
    radarr_client.request_post.return_value = {"id": 17}
    radarr_client.get_command.side_effect = [
        {"status": "started"},
        {"status": "completed", "result": "failed"},
        {"status": "completed", "result": "successful"},
    ]

    assert adapter.start_media_analysis() == 17
    assert adapter.get_command_status(17) == CommandStatus(False, False)
    assert adapter.get_command_status(17) == CommandStatus(True, False)
    assert adapter.get_command_status(17) == CommandStatus(True, True)
    radarr_client.request_post.assert_called_once_with(
        "/api/v3/command",
        json_data={"name": "RescanMovie", "priority": "high"},
    )
    radarr_client.get_command.assert_has_calls(
        [call(cid=17), call(cid=17), call(cid=17)]
    )


def test_maps_and_combines_file_rename_previews(
    adapter: RadarrAdapter, radarr_client: MagicMock
) -> None:
    movie_a = MediaItem(1, "Movie A", "/movies/Movie A")
    movie_b = MediaItem(2, "Movie B", "/movies/Movie B")
    radarr_client.request_get.side_effect = [
        [],
        [{"movieFileId": 10}, {"movieFileId": 11}],
    ]

    assert adapter.get_file_rename_candidate(movie_a) is None
    candidate_a = adapter.get_file_rename_candidate(movie_a)
    assert candidate_a == FileRenameCandidate(movie_a, (10, 11), "Movie A")
    assert adapter.build_file_rename_batches(()) == []

    candidate_b = FileRenameCandidate(movie_b, (20,), "Movie B")
    assert adapter.build_file_rename_batches((candidate_a, candidate_b)) == [
        FileRenameBatch((1, 2), (10, 11, 20), "Movie A, Movie B")
    ]
    radarr_client.request_get.assert_has_calls(
        [
            call(path="/api/v3/rename", url_params={"movieId": 1}),
            call(path="/api/v3/rename", url_params={"movieId": 1}),
        ]
    )


def test_starts_aggregate_movie_rename(
    adapter: RadarrAdapter, radarr_client: MagicMock
) -> None:
    batch = FileRenameBatch((1, 2), (10, 20), "Movie A, Movie B")
    radarr_client.request_post.return_value = {"id": 23}

    assert adapter.start_file_rename(batch) == 23
    radarr_client.request_post.assert_called_once_with(
        "/api/v3/command",
        json_data={"name": "RenameMovie", "movieIds": [1, 2]},
    )


def test_uses_radarr_folder_endpoints_and_payloads(
    adapter: RadarrAdapter, radarr_client: MagicMock
) -> None:
    movie_a = MediaItem(1, "Movie A", "/movies/Old A")
    movie_b = MediaItem(2, "Movie B", "/movies/Old B")
    batch = FolderRenameBatch("/movies", (movie_a, movie_b), False)
    radarr_client.get_root_folder.return_value = [
        {"path": "/movies"},
        {"path": "/movies-4k"},
    ]
    radarr_client.request_get.return_value = {"folder": "Movie A (2026)"}
    radarr_client.request_put.return_value = {}
    radarr_client.request_post.return_value = {"id": 29}

    assert adapter.list_root_folders() == ["/movies", "/movies-4k"]
    assert adapter.get_expected_folder_name(movie_a) == "Movie A (2026)"
    assert adapter.move_folder(batch) is None
    assert adapter.start_folder_rescan(batch) == 29
    radarr_client.request_get.assert_called_once_with(path="/api/v3/movie/1/folder")
    radarr_client.request_put.assert_called_once_with(
        path="/api/v3/movie/editor",
        json_data={
            "rootFolderPath": "/movies",
            "movieIds": [1, 2],
            "moveFiles": False,
        },
    )
    radarr_client.request_post.assert_called_once_with(
        "/api/v3/command",
        json_data={
            "priority": "high",
            "name": "RefreshMovie",
            "movieIds": [1, 2],
        },
    )


@pytest.mark.parametrize(
    ("boundary", "client_method"),
    [
        ("list", "get_movie"),
        ("setting", "request_get"),
        ("analysis", "request_post"),
        ("status", "get_command"),
        ("preview", "request_get"),
        ("rename", "request_post"),
        ("roots", "get_root_folder"),
        ("folder", "request_get"),
        ("move", "request_put"),
        ("rescan", "request_post"),
    ],
)
def test_translates_cliarr_errors_at_every_api_boundary(
    adapter: RadarrAdapter,
    radarr_client: MagicMock,
    boundary: str,
    client_method: str,
) -> None:
    item = MediaItem(1, "Movie", "/movies/Movie")
    file_batch = FileRenameBatch((1,), (10,), "Movie")
    folder_batch = FolderRenameBatch("/movies", (item,))
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
    getattr(radarr_client, client_method).side_effect = CliArrError("broken")

    with pytest.raises(ArrOperationError, match="failed: broken") as error:
        operations[boundary]()

    assert isinstance(error.value.__cause__, CliArrError)


def test_does_not_translate_unexpected_errors(
    adapter: RadarrAdapter, radarr_client: MagicMock
) -> None:
    radarr_client.get_movie.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        adapter.list_media_items()


@pytest.mark.parametrize(
    ("operation", "response", "message"),
    [
        ("list", RadarrMovieItem(id=1), "Expected a list of movies"),
        ("setting", [], "Expected an object response"),
        ("setting", {"enableMediaInfo": 1}, "Expected enableMediaInfo"),
        ("analysis", {"id": "1"}, "Expected a numeric command ID"),
        ("preview", {}, "Expected a list of rename previews"),
        ("preview", [[]], "Expected an object response"),
        (
            "preview",
            [{"movieFileId": "10"}],
            "Expected a movie file ID",
        ),
        ("roots", {}, "Expected a list of root folders"),
        ("folder", {"folder": 1}, "Expected a folder name"),
    ],
)
def test_rejects_malformed_radarr_responses(
    adapter: RadarrAdapter,
    radarr_client: MagicMock,
    operation: str,
    response: object,
    message: str,
) -> None:
    item = MediaItem(1, "Movie", "/movies/Movie")
    operations = {
        "list": (radarr_client.get_movie, adapter.list_media_items),
        "setting": (
            radarr_client.request_get,
            adapter.is_media_analysis_enabled,
        ),
        "analysis": (radarr_client.request_post, adapter.start_media_analysis),
        "preview": (
            radarr_client.request_get,
            lambda: adapter.get_file_rename_candidate(item),
        ),
        "roots": (radarr_client.get_root_folder, adapter.list_root_folders),
        "folder": (
            radarr_client.request_get,
            lambda: adapter.get_expected_folder_name(item),
        ),
    }
    client_call, adapter_call = operations[operation]
    client_call.return_value = response

    with pytest.raises(TypeError, match=message):
        adapter_call()
