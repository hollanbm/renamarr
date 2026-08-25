from renamarr.models.media import FolderRenameBatch, MediaItem


def test_folder_rename_batch_exposes_ids_and_titles() -> None:
    items = (
        MediaItem(1, "A", "/root/a"),
        MediaItem(2, "B", "/root/b"),
    )

    batch = FolderRenameBatch("/root", items)

    assert batch.item_ids == (1, 2)
    assert batch.titles == ("A", "B")
