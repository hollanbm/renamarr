from unittest.mock import MagicMock, call

import pytest
from pytest_mock import MockerFixture
from radarr import (
    CommandResource,
    MediaManagementConfigResource,
    MovieEditorResource,
    MovieResource,
    RenameMovieResource,
    RootFolderResource,
)
from radarr import CommandResult as RadarrCommandResult
from radarr import CommandStatus as RadarrCommandStatus
from radarr.rest import ApiException

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
def radarr_apis(mocker: MockerFixture) -> dict[str, MagicMock]:
    mocker.patch("renamarr.radarr.radarr_adapter.ApiClient", autospec=True)
    return {
        name: mocker.patch(
            f"renamarr.radarr.radarr_adapter.{name}", autospec=True
        ).return_value
        for name in (
            "MovieApi",
            "MediaManagementConfigApi",
            "CommandApi",
            "RenameMovieApi",
            "RootFolderApi",
            "MovieFolderApi",
            "MovieEditorApi",
        )
    }


def test_wires_generated_radarr_client(mocker: MockerFixture) -> None:
    configuration = mocker.patch(
        "renamarr.radarr.radarr_adapter.Configuration", autospec=True
    )
    api_client = mocker.patch("renamarr.radarr.radarr_adapter.ApiClient", autospec=True)
    api_classes = [
        mocker.patch(f"renamarr.radarr.radarr_adapter.{name}", autospec=True)
        for name in (
            "MovieApi",
            "MediaManagementConfigApi",
            "CommandApi",
            "RenameMovieApi",
            "RootFolderApi",
            "MovieFolderApi",
            "MovieEditorApi",
        )
    ]

    adapter = RadarrAdapter("https://radarr.test", "radarr-key")

    configuration.assert_called_once_with(
        host="https://radarr.test",
        api_key={"X-Api-Key": "radarr-key"},
    )
    api_client.assert_called_once_with(configuration.return_value)
    assert adapter._client is api_client.return_value
    for api_class in api_classes:
        api_class.assert_called_once_with(api_client.return_value)


@pytest.fixture
def adapter(radarr_apis: dict[str, MagicMock]) -> RadarrAdapter:
    return RadarrAdapter("https://radarr.test", "api-key")


def test_maps_movies_to_shared_media_items(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    movie_api = radarr_apis["MovieApi"]
    movie_api.list_movie.return_value = [
        MovieResource(id=2, title="Movie B", path="/movies/Movie B"),
        MovieResource(id=1, title="Movie A", path="/movies/Movie A"),
    ]

    assert adapter.list_media_items() == [
        MediaItem(id=2, title="Movie B", path="/movies/Movie B"),
        MediaItem(id=1, title="Movie A", path="/movies/Movie A"),
    ]
    movie_api.list_movie.assert_called_once_with()


@pytest.mark.parametrize("enabled", [True, False])
def test_reads_media_analysis_setting(
    adapter: RadarrAdapter,
    radarr_apis: dict[str, MagicMock],
    enabled: bool,
) -> None:
    media_management_api = radarr_apis["MediaManagementConfigApi"]
    media_management_api.get_media_management_config.return_value = (
        MediaManagementConfigResource(enable_media_info=enabled)
    )

    assert adapter.is_media_analysis_enabled() is enabled
    media_management_api.get_media_management_config.assert_called_once_with()


def test_starts_media_analysis_and_maps_command_status(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    command_api = radarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=17)
    command_api.get_command_by_id.side_effect = [
        CommandResource(status=RadarrCommandStatus.STARTED),
        CommandResource(
            status=RadarrCommandStatus.COMPLETED,
            result=RadarrCommandResult.UNSUCCESSFUL,
        ),
        CommandResource(
            status=RadarrCommandStatus.COMPLETED,
            result=RadarrCommandResult.SUCCESSFUL,
        ),
    ]

    assert adapter.start_media_analysis() == 17
    assert adapter.get_command_status(17) == CommandStatus(False, False)
    assert adapter.get_command_status(17) == CommandStatus(True, False)
    assert adapter.get_command_status(17) == CommandStatus(True, True)
    command_api.create_command.assert_called_once()
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RescanMovie",
        "priority": "high",
    }
    assert command_api.get_command_by_id.call_args_list == [
        call(17),
        call(17),
        call(17),
    ]


def test_maps_and_combines_file_rename_previews(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    movie_a = MediaItem(1, "Movie A", "/movies/Movie A")
    movie_b = MediaItem(2, "Movie B", "/movies/Movie B")
    rename_api = radarr_apis["RenameMovieApi"]
    rename_api.list_rename.side_effect = [
        [],
        [
            RenameMovieResource(movie_file_id=10),
            RenameMovieResource(movie_file_id=11),
        ],
    ]

    assert adapter.get_file_rename_candidate(movie_a) is None
    candidate_b = adapter.get_file_rename_candidate(movie_b)
    assert candidate_b == FileRenameCandidate(movie_b, (10, 11), "Movie B")
    assert adapter.build_file_rename_batches(()) == []

    movie_c = MediaItem(3, "Movie C", "/movies/Movie C")
    candidate_c = FileRenameCandidate(movie_c, (20,), "Movie C")
    assert adapter.build_file_rename_batches((candidate_b, candidate_c)) == [
        FileRenameBatch((2, 3), (10, 11, 20), "Movie B, Movie C")
    ]
    assert rename_api.list_rename.call_args_list == [
        call(movie_id=[1]),
        call(movie_id=[2]),
    ]


def test_starts_aggregate_movie_rename(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    batch = FileRenameBatch((1, 2), (10, 20), "Movie A, Movie B")
    command_api = radarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=23)

    assert adapter.start_file_rename(batch) == 23
    command_api.create_command.assert_called_once()
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RenameMovie",
        "movieIds": [1, 2],
    }


def test_uses_radarr_folder_endpoints_and_payloads(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    movie_a = MediaItem(1, "Movie A", "/movies/Old A")
    movie_b = MediaItem(2, "Movie B", "/movies/Old B")
    batch = FolderRenameBatch("/movies", (movie_a, movie_b), False)
    root_folder_api = radarr_apis["RootFolderApi"]
    root_folder_api.list_root_folder.return_value = [
        RootFolderResource(path="/movies"),
        RootFolderResource(path="/movies-4k"),
    ]
    movie_folder_api = radarr_apis["MovieFolderApi"]
    folder_response = MagicMock(status=200)
    folder_response.read.return_value = b'{"folder": "Movie A (2026)"}'
    movie_folder_api.get_movie_folder_without_preload_content.return_value = (
        folder_response
    )
    command_api = radarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=29)

    assert adapter.list_root_folders() == ["/movies", "/movies-4k"]
    assert adapter.get_expected_folder_name(movie_a) == "Movie A (2026)"
    assert adapter.move_folder(batch) is None
    assert adapter.start_folder_rescan(batch) == 29
    root_folder_api.list_root_folder.assert_called_once_with()
    movie_folder_api.get_movie_folder_without_preload_content.assert_called_once_with(
        id=1
    )
    folder_response.read.assert_called_once_with()
    folder_response.release_conn.assert_called_once_with()
    movie_editor_api = radarr_apis["MovieEditorApi"]
    movie_editor_api.put_movie_editor.assert_called_once()
    editor = movie_editor_api.put_movie_editor.call_args.args[0]
    assert isinstance(editor, MovieEditorResource)
    assert editor.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "movieIds": [1, 2],
        "rootFolderPath": "/movies",
        "moveFiles": False,
    }
    command_api.create_command.assert_called_once()
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RefreshMovie",
        "priority": "high",
        "movieIds": [1, 2],
    }


@pytest.mark.parametrize(
    ("boundary", "api_name", "method_name", "error_context"),
    [
        ("list", "MovieApi", "list_movie", "List Radarr movies"),
        (
            "setting",
            "MediaManagementConfigApi",
            "get_media_management_config",
            "Read Radarr media-management settings",
        ),
        ("analysis", "CommandApi", "create_command", "Start Radarr media analysis"),
        ("status", "CommandApi", "get_command_by_id", "Read Radarr command status"),
        (
            "preview",
            "RenameMovieApi",
            "list_rename",
            "Preview Radarr file rename for Movie",
        ),
        ("rename", "CommandApi", "create_command", "Start Radarr file rename"),
        ("roots", "RootFolderApi", "list_root_folder", "List Radarr root folders"),
        (
            "folder",
            "MovieFolderApi",
            "get_movie_folder_without_preload_content",
            "Resolve Radarr folder for Movie",
        ),
        ("move", "MovieEditorApi", "put_movie_editor", "Move Radarr movie folders"),
        ("rescan", "CommandApi", "create_command", "Start Radarr folder rescan"),
    ],
)
def test_translates_api_errors_at_every_boundary(
    adapter: RadarrAdapter,
    radarr_apis: dict[str, MagicMock],
    boundary: str,
    api_name: str,
    method_name: str,
    error_context: str,
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
    api_error = ApiException(reason="broken")
    getattr(radarr_apis[api_name], method_name).side_effect = api_error

    with pytest.raises(ArrOperationError) as error:
        operations[boundary]()

    assert str(error.value).split(" failed:", maxsplit=1)[0] == error_context
    assert error.value.__cause__ is api_error
    assert "broken" in str(error.value)


def test_does_not_translate_unexpected_errors(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    radarr_apis["MovieApi"].list_movie.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        adapter.list_media_items()


@pytest.mark.parametrize(
    ("operation", "response", "message"),
    [
        ("list", MovieResource(id=1), "Expected a list of movies"),
        (
            "setting",
            MediaManagementConfigResource(),
            "Expected enableMediaInfo",
        ),
        (
            "analysis",
            CommandResource(),
            "^Expected a numeric command ID from Radarr$",
        ),
        ("preview", {}, "Expected a list of rename previews"),
        ("roots", {}, "Expected a list of root folders"),
    ],
)
def test_rejects_malformed_top_level_responses(
    adapter: RadarrAdapter,
    radarr_apis: dict[str, MagicMock],
    operation: str,
    response: object,
    message: str,
) -> None:
    item = MediaItem(1, "Movie", "/movies/Movie")
    operations = {
        "list": (radarr_apis["MovieApi"].list_movie, adapter.list_media_items),
        "setting": (
            radarr_apis["MediaManagementConfigApi"].get_media_management_config,
            adapter.is_media_analysis_enabled,
        ),
        "analysis": (
            radarr_apis["CommandApi"].create_command,
            adapter.start_media_analysis,
        ),
        "preview": (
            radarr_apis["RenameMovieApi"].list_rename,
            lambda: adapter.get_file_rename_candidate(item),
        ),
        "roots": (
            radarr_apis["RootFolderApi"].list_root_folder,
            adapter.list_root_folders,
        ),
    }
    client_call, adapter_call = operations[operation]
    client_call.return_value = response

    with pytest.raises(TypeError, match=message):
        adapter_call()


@pytest.mark.parametrize(
    ("movie", "message"),
    [
        (MovieResource(title="Movie", path="/movies/Movie"), "Expected a movie ID"),
        (MovieResource(id=1, path="/movies/Movie"), "Expected a movie title"),
        (MovieResource(id=1, title="Movie"), "Expected a movie path"),
    ],
)
def test_rejects_movies_missing_required_fields(
    adapter: RadarrAdapter,
    radarr_apis: dict[str, MagicMock],
    movie: MovieResource,
    message: str,
) -> None:
    radarr_apis["MovieApi"].list_movie.return_value = [movie]

    with pytest.raises(TypeError, match=message):
        adapter.list_media_items()


def test_rejects_rename_preview_missing_movie_file_id(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    radarr_apis["RenameMovieApi"].list_rename.return_value = [RenameMovieResource()]

    with pytest.raises(TypeError, match="Expected a movie file ID"):
        adapter.get_file_rename_candidate(MediaItem(1, "Movie", "/movies/Movie"))


def test_rejects_root_folder_missing_path(
    adapter: RadarrAdapter, radarr_apis: dict[str, MagicMock]
) -> None:
    radarr_apis["RootFolderApi"].list_root_folder.return_value = [RootFolderResource()]

    with pytest.raises(TypeError, match="Expected a root-folder path"):
        adapter.list_root_folders()


@pytest.mark.parametrize("status", [199, 300])
def test_rejects_non_successful_folder_response_before_parsing(
    adapter: RadarrAdapter,
    radarr_apis: dict[str, MagicMock],
    status: int,
) -> None:
    folder_response = MagicMock(status=status, reason="Unexpected status")
    folder_response.read.return_value = b"not json"
    radarr_apis[
        "MovieFolderApi"
    ].get_movie_folder_without_preload_content.return_value = folder_response

    with pytest.raises(
        ArrOperationError, match="Resolve Radarr folder.*failed"
    ) as error:
        adapter.get_expected_folder_name(MediaItem(1, "Movie", "/movies/Movie"))

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
    adapter: RadarrAdapter,
    radarr_apis: dict[str, MagicMock],
    payload: bytes,
    message: str,
) -> None:
    folder_response = MagicMock(status=200)
    folder_response.read.return_value = payload
    radarr_apis[
        "MovieFolderApi"
    ].get_movie_folder_without_preload_content.return_value = folder_response

    with pytest.raises(TypeError, match=message):
        adapter.get_expected_folder_name(MediaItem(1, "Movie", "/movies/Movie"))

    folder_response.release_conn.assert_called_once_with()
