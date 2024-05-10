from batch_rename import BatchRename
from rename import Rename


class TestBatchRename:
    def test_empty_list_has_files_to_rename_test(self) -> None:
        batch_rename = BatchRename()
        assert not batch_rename.has_files_to_rename()

    def test_has_files_to_rename(self) -> None:
        batch_rename = BatchRename()
        batch_rename.append(Rename(1, "S01E01"))
        assert batch_rename.has_files_to_rename()

    def test_singular_get_log_msg(self) -> None:
        batch_rename = BatchRename()
        batch_rename.append(Rename(1, "S01E01"))
        assert batch_rename.get_log_message() == "S01E01"

    def test_multiples_get_log_msg(self) -> None:
        batch_rename = BatchRename()
        batch_rename.append(Rename(1, "S01E01"))
        batch_rename.append(Rename(2, "S01E02"))
        assert batch_rename.get_log_message() == "S01E01, S01E02"

    def test_singular_get_file_ids(self) -> None:
        batch_rename = BatchRename()
        batch_rename.append(Rename(1, "S01E01"))
        assert batch_rename.get_file_ids() == [1]

    def test_multiple_get_file_ids(self) -> None:
        batch_rename = BatchRename()
        batch_rename.append(Rename(1, "S01E01"))
        batch_rename.append(Rename(2, "S01E02"))
        assert batch_rename.get_file_ids() == [1, 2]
