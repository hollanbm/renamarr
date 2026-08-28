from unittest.mock import MagicMock, call

import pytest
from lidarr import (
    ArtistEditorResource,
    ArtistResource,
    CommandResource,
    RenameTrackResource,
    RootFolderResource,
)
from lidarr import CommandResult as LidarrCommandResult
from lidarr import CommandStatus as LidarrCommandStatus
from lidarr.rest import ApiException
from pytest_mock import MockerFixture

from renamarr.exceptions import ArrOperationError
from renamarr.lidarr.lidarr_adapter import LidarrAdapter
from renamarr.models.command import CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)


@pytest.fixture
def lidarr_apis(mocker: MockerFixture) -> dict[str, MagicMock]:
    mocker.patch("renamarr.lidarr.lidarr_adapter.ApiClient", autospec=True)
    return {
        name: mocker.patch(
            f"renamarr.lidarr.lidarr_adapter.{name}", autospec=True
        ).return_value
        for name in (
            "ArtistApi",
            "ArtistLookupApi",
            "CommandApi",
            "RenameTrackApi",
            "RootFolderApi",
            "ArtistEditorApi",
        )
    }


def test_wires_generated_lidarr_client(mocker: MockerFixture) -> None:
    configuration = mocker.patch(
        "renamarr.lidarr.lidarr_adapter.Configuration", autospec=True
    )
    api_client = mocker.patch("renamarr.lidarr.lidarr_adapter.ApiClient", autospec=True)
    pool_manager = mocker.Mock()
    api_client.return_value.rest_client = mocker.Mock(pool_manager=pool_manager)
    api_classes = [
        mocker.patch(f"renamarr.lidarr.lidarr_adapter.{name}", autospec=True)
        for name in (
            "ArtistApi",
            "ArtistLookupApi",
            "CommandApi",
            "RenameTrackApi",
            "RootFolderApi",
            "ArtistEditorApi",
        )
    ]

    adapter = LidarrAdapter("https://lidarr.test", "lidarr-key")

    configuration.assert_called_once_with(
        host="https://lidarr.test",
        api_key={"X-Api-Key": "lidarr-key"},
    )
    api_client.assert_called_once_with(configuration.return_value)
    assert adapter._client is api_client.return_value
    for api_class in api_classes:
        api_class.assert_called_once_with(api_client.return_value)

    adapter.close()

    pool_manager.clear.assert_called_once_with()


@pytest.fixture
def adapter(lidarr_apis: dict[str, MagicMock]) -> LidarrAdapter:
    return LidarrAdapter("https://lidarr.test", "api-key")


def test_maps_artists_to_shared_media_items(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    artist_api = lidarr_apis["ArtistApi"]
    artist_api.list_artist.return_value = [
        ArtistResource(
            id=2,
            artist_name="Artist B",
            path="/music/Artist B",
            foreign_artist_id="artist-b-id",
        ),
        ArtistResource(
            id=1,
            artist_name="Artist A",
            path="/music/Artist A",
            foreign_artist_id="artist-a-id",
        ),
    ]

    assert adapter.list_media_items() == [
        MediaItem(id=2, title="Artist B", path="/music/Artist B"),
        MediaItem(id=1, title="Artist A", path="/music/Artist A"),
    ]
    artist_api.list_artist.assert_called_once_with()


def test_media_analysis_is_always_available_and_starts_folder_rescan(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    command_api = lidarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=17)

    assert adapter.is_media_analysis_enabled() is True
    assert adapter.start_media_analysis() == 17
    command_api.create_command.assert_called_once()
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RescanFolders",
        "priority": "high",
        "filter": "known",
        "addNewArtists": False,
    }


def test_maps_command_status(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    command_api = lidarr_apis["CommandApi"]
    command_api.get_command_by_id.side_effect = [
        CommandResource(status=LidarrCommandStatus.STARTED),
        CommandResource(
            status=LidarrCommandStatus.COMPLETED,
            result=LidarrCommandResult.UNSUCCESSFUL,
        ),
        CommandResource(
            status=LidarrCommandStatus.COMPLETED,
            result=LidarrCommandResult.SUCCESSFUL,
        ),
    ]

    assert adapter.get_command_status(17) == CommandStatus(False, False)
    assert adapter.get_command_status(17) == CommandStatus(True, False)
    assert adapter.get_command_status(17) == CommandStatus(True, True)
    assert command_api.get_command_by_id.call_args_list == [
        call(17),
        call(17),
        call(17),
    ]


def test_maps_track_rename_previews_and_builds_per_artist_batches(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    artist_a = MediaItem(1, "Artist A", "/music/Artist A")
    artist_b = MediaItem(2, "Artist B", "/music/Artist B")
    rename_api = lidarr_apis["RenameTrackApi"]
    rename_api.list_rename.side_effect = [
        [],
        [
            RenameTrackResource(track_file_id=10),
            RenameTrackResource(track_file_id=20),
        ],
    ]

    assert adapter.get_file_rename_candidate(artist_a) is None
    candidate_b = adapter.get_file_rename_candidate(artist_b)
    assert candidate_b == FileRenameCandidate(
        artist_b,
        (10, 20),
        "Artist B",
    )
    artist_c = MediaItem(3, "Artist C", "/music/Artist C")
    candidate_c = FileRenameCandidate(artist_c, (30,), "Artist C")
    assert adapter.build_file_rename_batches((candidate_b, candidate_c)) == [
        FileRenameBatch((2,), (10, 20), "Artist B"),
        FileRenameBatch((3,), (30,), "Artist C"),
    ]
    assert adapter.build_file_rename_batches(()) == []
    assert rename_api.list_rename.call_args_list == [
        call(artist_id=1),
        call(artist_id=2),
    ]


def test_starts_artist_file_rename(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    batch = FileRenameBatch((7,), (10, 20), "Artist")
    command_api = lidarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=23)

    assert adapter.start_file_rename(batch) == 23
    command_api.create_command.assert_called_once()
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RenameFiles",
        "artistId": 7,
        "files": [10, 20],
    }


def test_uses_lidarr_folder_endpoints_and_caches_expected_folders(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    artist = MediaItem(1, "Artist", "/music/Old Artist")
    artist_api = lidarr_apis["ArtistApi"]
    artist_api.list_artist.return_value = [
        ArtistResource(
            id=1,
            artist_name="Artist",
            path="/music/Old Artist",
            foreign_artist_id="artist-id",
        )
    ]
    root_folder_api = lidarr_apis["RootFolderApi"]
    root_folder_api.list_root_folder.return_value = [
        RootFolderResource(path="/music"),
        RootFolderResource(path="/music-lossless"),
    ]
    artist_lookup_api = lidarr_apis["ArtistLookupApi"]
    artist_lookup_api.list_artist_lookup.return_value = [
        ArtistResource(foreign_artist_id="other-id", folder="Other Artist"),
        ArtistResource(foreign_artist_id="artist-id", folder="A/Artist (2026)"),
    ]
    command_api = lidarr_apis["CommandApi"]
    command_api.create_command.return_value = CommandResource(id=29)
    batch = FolderRenameBatch("/music", (artist,), False)

    adapter.list_media_items()
    assert adapter.list_root_folders() == ["/music", "/music-lossless"]
    assert adapter.get_expected_folder_name(artist) == "A/Artist (2026)"
    assert adapter.get_expected_folder_name(artist) == "A/Artist (2026)"
    assert adapter.move_folder(batch) is None
    assert adapter.start_folder_rescan(batch) == 29

    artist_lookup_api.list_artist_lookup.assert_called_once_with(
        term="lidarr:artist-id"
    )
    artist_api.get_artist_by_id.assert_not_called()
    root_folder_api.list_root_folder.assert_called_once_with()
    artist_editor_api = lidarr_apis["ArtistEditorApi"]
    artist_editor_api.put_artist_editor.assert_called_once()
    editor = artist_editor_api.put_artist_editor.call_args.args[0]
    assert isinstance(editor, ArtistEditorResource)
    assert editor.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "artistIds": [1],
        "rootFolderPath": "/music",
        "moveFiles": False,
    }
    command_api.create_command.assert_called_once()
    command = command_api.create_command.call_args.args[0]
    assert command.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "name": "RescanFolders",
        "priority": "high",
        "artistIds": [1],
        "folders": ["/music/A/Artist (2026)"],
        "filter": "known",
        "addNewArtists": False,
    }


def test_fetches_artist_when_folder_cache_was_not_seeded(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    item = MediaItem(7, "Artist", "/music/Artist")
    lidarr_apis["ArtistApi"].get_artist_by_id.return_value = ArtistResource(
        id=7,
        foreign_artist_id="artist-id",
    )
    lidarr_apis["ArtistLookupApi"].list_artist_lookup.return_value = [
        ArtistResource(foreign_artist_id="artist-id", folder="Artist (2026)")
    ]

    assert adapter.get_expected_folder_name(item) == "Artist (2026)"
    lidarr_apis["ArtistApi"].get_artist_by_id.assert_called_once_with(7)


@pytest.mark.parametrize(
    ("boundary", "api_name", "method_name", "error_context"),
    [
        ("list", "ArtistApi", "list_artist", "List Lidarr artists"),
        ("analysis", "CommandApi", "create_command", "Start Lidarr media analysis"),
        ("status", "CommandApi", "get_command_by_id", "Read Lidarr command status"),
        (
            "preview",
            "RenameTrackApi",
            "list_rename",
            "Preview Lidarr file rename for Artist",
        ),
        ("rename", "CommandApi", "create_command", "Start Lidarr file rename"),
        ("roots", "RootFolderApi", "list_root_folder", "List Lidarr root folders"),
        ("artist", "ArtistApi", "get_artist_by_id", "Read Lidarr artist Artist"),
        (
            "folder",
            "ArtistLookupApi",
            "list_artist_lookup",
            "Resolve Lidarr folder for Artist",
        ),
        (
            "move",
            "ArtistEditorApi",
            "put_artist_editor",
            "Move Lidarr artist folders",
        ),
        ("rescan", "CommandApi", "create_command", "Start Lidarr folder rescan"),
    ],
)
def test_translates_api_errors_at_every_boundary(
    adapter: LidarrAdapter,
    lidarr_apis: dict[str, MagicMock],
    boundary: str,
    api_name: str,
    method_name: str,
    error_context: str,
) -> None:
    item = MediaItem(1, "Artist", "/music/Artist")
    file_batch = FileRenameBatch((1,), (10,), "Artist")
    folder_batch = FolderRenameBatch("/music", (item,))
    if boundary in {"folder", "rescan"}:
        adapter._artists[item.id] = ArtistResource(
            id=item.id,
            foreign_artist_id="artist-id",
        )
    if boundary == "rescan":
        adapter._expected_folders[item.id] = "Artist"
    operations = {
        "list": adapter.list_media_items,
        "analysis": adapter.start_media_analysis,
        "status": lambda: adapter.get_command_status(1),
        "preview": lambda: adapter.get_file_rename_candidate(item),
        "rename": lambda: adapter.start_file_rename(file_batch),
        "roots": adapter.list_root_folders,
        "artist": lambda: adapter.get_expected_folder_name(item),
        "folder": lambda: adapter.get_expected_folder_name(item),
        "move": lambda: adapter.move_folder(folder_batch),
        "rescan": lambda: adapter.start_folder_rescan(folder_batch),
    }
    api_error = ApiException(reason="broken")
    getattr(lidarr_apis[api_name], method_name).side_effect = api_error

    with pytest.raises(ArrOperationError) as error:
        operations[boundary]()

    assert str(error.value).split(" failed:", maxsplit=1)[0] == error_context
    assert error.value.__cause__ is api_error
    assert "broken" in str(error.value)


def test_does_not_translate_unexpected_errors(
    adapter: LidarrAdapter, lidarr_apis: dict[str, MagicMock]
) -> None:
    lidarr_apis["ArtistApi"].list_artist.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        adapter.list_media_items()


@pytest.mark.parametrize(
    ("operation", "response", "message"),
    [
        ("list", ArtistResource(id=1), "Expected a list of artists"),
        ("analysis", CommandResource(), "^Expected a numeric command ID from Lidarr$"),
        ("preview", {}, "Expected a list of rename previews"),
        ("roots", {}, "Expected a list of root folders"),
        ("lookup", {}, "Expected a list of artist lookup results"),
    ],
)
def test_rejects_malformed_top_level_responses(
    adapter: LidarrAdapter,
    lidarr_apis: dict[str, MagicMock],
    operation: str,
    response: object,
    message: str,
) -> None:
    item = MediaItem(1, "Artist", "/music/Artist")
    adapter._artists[item.id] = ArtistResource(
        id=item.id,
        foreign_artist_id="artist-id",
    )
    operations = {
        "list": (lidarr_apis["ArtistApi"].list_artist, adapter.list_media_items),
        "analysis": (
            lidarr_apis["CommandApi"].create_command,
            adapter.start_media_analysis,
        ),
        "preview": (
            lidarr_apis["RenameTrackApi"].list_rename,
            lambda: adapter.get_file_rename_candidate(item),
        ),
        "roots": (
            lidarr_apis["RootFolderApi"].list_root_folder,
            adapter.list_root_folders,
        ),
        "lookup": (
            lidarr_apis["ArtistLookupApi"].list_artist_lookup,
            lambda: adapter.get_expected_folder_name(item),
        ),
    }
    api_method, adapter_method = operations[operation]
    api_method.return_value = response

    with pytest.raises(TypeError, match=message):
        adapter_method()


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ("artist-id", "Expected an artist ID"),
        ("artist-name", "Expected an artist name"),
        ("artist-path", "Expected an artist path"),
        ("track-file", "Expected a track file ID"),
        ("root-path", "Expected a root-folder path"),
        ("foreign-id", "Expected a foreign artist ID"),
        ("lookup-match", "Expected an exact artist lookup result"),
        ("folder", "Expected an artist folder"),
    ],
)
def test_rejects_missing_required_response_fields(
    adapter: LidarrAdapter,
    lidarr_apis: dict[str, MagicMock],
    operation: str,
    message: str,
) -> None:
    item = MediaItem(1, "Artist", "/music/Artist")
    artist_api = lidarr_apis["ArtistApi"]
    rename_api = lidarr_apis["RenameTrackApi"]
    root_folder_api = lidarr_apis["RootFolderApi"]
    artist_lookup_api = lidarr_apis["ArtistLookupApi"]
    if operation == "artist-id":
        artist_api.list_artist.return_value = [
            ArtistResource(artist_name="Artist", path="/music/Artist")
        ]
        action = adapter.list_media_items
    elif operation == "artist-name":
        artist_api.list_artist.return_value = [
            ArtistResource(id=1, path="/music/Artist")
        ]
        action = adapter.list_media_items
    elif operation == "artist-path":
        artist_api.list_artist.return_value = [
            ArtistResource(id=1, artist_name="Artist")
        ]
        action = adapter.list_media_items
    elif operation == "track-file":
        rename_api.list_rename.return_value = [RenameTrackResource()]
        action = lambda: adapter.get_file_rename_candidate(item)
    elif operation == "root-path":
        root_folder_api.list_root_folder.return_value = [RootFolderResource()]
        action = adapter.list_root_folders
    else:
        foreign_artist_id = None if operation == "foreign-id" else "artist-id"
        adapter._artists[item.id] = ArtistResource(
            id=item.id,
            foreign_artist_id=foreign_artist_id,
        )
        if operation == "lookup-match":
            artist_lookup_api.list_artist_lookup.return_value = []
        else:
            artist_lookup_api.list_artist_lookup.return_value = [
                ArtistResource(foreign_artist_id="artist-id")
            ]
        action = lambda: adapter.get_expected_folder_name(item)

    with pytest.raises(TypeError, match=message):
        action()
