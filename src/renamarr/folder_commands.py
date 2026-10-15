from collections import Counter

from pydantic import AliasChoices, BaseModel, Field, TypeAdapter, ValidationError

from renamarr.exceptions import ArrOperationError
from renamarr.models.media import FolderRenameBatch


class _FolderMoveItem(BaseModel):
    item_id: int = Field(validation_alias=AliasChoices("movieId", "seriesId"))
    source_path: str = Field(alias="sourcePath")


class _FolderMoveBody(BaseModel):
    destination_root: str | None = Field(default=None, alias="destinationRootFolder")
    items: list[_FolderMoveItem] = Field(
        default_factory=list, validation_alias=AliasChoices("movies", "series")
    )


class FolderMoveCommand(BaseModel):
    """Command-list fields needed to identify an editor's folder move."""

    id: int
    name: str
    status: str
    body: _FolderMoveBody


def parse_folder_commands(payload: bytes) -> list[FolderMoveCommand]:
    """Read command bodies omitted by the generated Arr clients."""
    try:
        return TypeAdapter(list[FolderMoveCommand]).validate_json(payload)
    except ValidationError as error:
        raise ArrOperationError("Invalid folder move command-list response") from error


def find_folder_move_command(
    before: list[FolderMoveCommand],
    after: list[FolderMoveCommand],
    batch: FolderRenameBatch,
    command_name: str,
) -> int:
    """Identify a new move command or an exact active command reused by Arr."""
    previous_ids = {command.id for command in before}
    expected_items = Counter((item.id, item.path) for item in batch.items)
    matches = [
        command
        for command in after
        if command.name == command_name
        and command.body.destination_root == batch.root_folder_path
        and Counter((item.item_id, item.source_path) for item in command.body.items)
        == expected_items
    ]
    candidates = [command for command in matches if command.id not in previous_ids]
    if not candidates:
        active_ids = {
            command.id for command in before if command.status in {"queued", "started"}
        }
        candidates = [command for command in matches if command.id in active_ids]
    if len(candidates) != 1:
        raise ArrOperationError(
            f"Expected one matching {command_name} command, found {len(candidates)}"
        )
    return candidates[0].id
