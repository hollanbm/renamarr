from json import dumps

import pytest

from renamarr.exceptions import ArrOperationError
from renamarr.folder_commands import find_folder_move_command, parse_folder_commands
from renamarr.models.media import FolderRenameBatch, MediaItem


@pytest.mark.parametrize("service", ["Movie", "Series"])
@pytest.mark.parametrize(
    ("before_status", "after_status", "new_ids", "expected"),
    [
        ("completed", "queued", [2], 2),
        ("completed", "completed", [2], 2),
        ("queued", "queued", [], 1),
        ("started", "started", [], 1),
        ("started", "completed", [], 1),
        ("queued", "queued", [2], 2),
        ("completed", "completed", [], None),
        ("failed", "failed", [], None),
        ("queued", "queued", [2, 3], None),
    ],
)
def test_matches_new_or_deduplicated_moves(
    service: str,
    before_status: str,
    after_status: str,
    new_ids: list[int],
    expected: int | None,
) -> None:
    name = f"BulkMove{service}"
    items_key = "movies" if service == "Movie" else "series"
    id_key = "movieId" if service == "Movie" else "seriesId"

    def command(command_id: int, status: str) -> dict[str, object]:
        return {
            "id": command_id,
            "name": name,
            "status": status,
            "body": {
                "destinationRootFolder": "/root",
                items_key: [
                    {id_key: 2, "sourcePath": "/root/old-b"},
                    {id_key: 1, "sourcePath": "/root/old-a"},
                ],
            },
        }

    before = parse_folder_commands(dumps([command(1, before_status)]).encode())
    after = parse_folder_commands(
        dumps(
            [command(1, after_status)]
            + [command(command_id, after_status) for command_id in new_ids]
        ).encode()
    )
    batch = FolderRenameBatch(
        "/root", (MediaItem(1, "A", "/root/old-a"), MediaItem(2, "B", "/root/old-b"))
    )

    if expected is None:
        with pytest.raises(ArrOperationError, match="Expected one matching"):
            find_folder_move_command(before, after, batch, name)
    else:
        assert find_folder_move_command(before, after, batch, name) == expected


@pytest.mark.parametrize(
    "payload",
    [
        b'[{"id": 1, "name": "Other", "status": "queued", "body": {}}]',
        b'[{"id": 1, "name": "BulkMoveMovie", "status": "queued", "body": {}}]',
        b'[{"id": 1, "name": "BulkMoveMovie", "status": "queued", "body": {"destinationRootFolder": "/other"}}]',
        b'[{"id": 1, "name": "BulkMoveMovie", "status": "queued", "body": {"destinationRootFolder": "/root", "movies": [{"movieId": 1, "sourcePath": "/root/different"}]}}]',
        b'[{"id": 1, "name": "BulkMoveMovie", "status": "queued", "body": {"destinationRootFolder": "/root", "movies": [{"movieId": 2, "sourcePath": "/root/old"}]}}]',
        b'[{"id": 1, "name": "BulkMoveMovie", "status": "queued", "body": {"destinationRootFolder": "/root", "movies": [{"movieId": 1, "sourcePath": "/root/old"}, {"movieId": 1, "sourcePath": "/root/old"}]}}]',
    ],
)
def test_rejects_unrelated_or_inexact_commands(payload: bytes) -> None:
    batch = FolderRenameBatch("/root", (MediaItem(1, "A", "/root/old"),))

    with pytest.raises(ArrOperationError, match="found 0"):
        find_folder_move_command(
            [], parse_folder_commands(payload), batch, "BulkMoveMovie"
        )


def test_rejects_ambiguous_deduplicated_moves() -> None:
    payload = b'[{"id": 1, "name": "BulkMoveMovie", "status": "queued", "body": {"destinationRootFolder": "/root", "movies": [{"movieId": 1, "sourcePath": "/root/old"}]}}, {"id": 2, "name": "BulkMoveMovie", "status": "started", "body": {"destinationRootFolder": "/root", "movies": [{"movieId": 1, "sourcePath": "/root/old"}]}}]'
    commands = parse_folder_commands(payload)
    batch = FolderRenameBatch("/root", (MediaItem(1, "A", "/root/old"),))

    with pytest.raises(ArrOperationError, match="found 2"):
        find_folder_move_command(commands, commands, batch, "BulkMoveMovie")


@pytest.mark.parametrize("payload", [b"invalid", b"{}", b"[{}]"])
def test_translates_invalid_command_lists(payload: bytes) -> None:
    with pytest.raises(ArrOperationError, match="Invalid folder move command-list"):
        parse_folder_commands(payload)
