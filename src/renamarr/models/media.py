from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaItem:
    """A media item managed by an Arr service."""

    id: int
    title: str
    path: str


@dataclass(frozen=True, slots=True)
class FileRenameCandidate:
    """An item whose files need to be renamed."""

    item: MediaItem
    file_ids: tuple[int, ...]
    description: str


@dataclass(frozen=True, slots=True)
class FileRenameBatch:
    """A file rename operation that can be submitted as one command."""

    item_ids: tuple[int, ...]
    file_ids: tuple[int, ...]
    description: str


@dataclass(frozen=True, slots=True)
class FolderRenameBatch:
    """Media folders that can be moved together under one root folder."""

    root_folder_path: str
    items: tuple[MediaItem, ...]
    move_files: bool = True

    @property
    def item_ids(self) -> tuple[int, ...]:
        """Return the IDs of the items in this batch."""
        return tuple(item.id for item in self.items)

    @property
    def titles(self) -> tuple[str, ...]:
        """Return the titles of the items in this batch."""
        return tuple(item.title for item in self.items)
