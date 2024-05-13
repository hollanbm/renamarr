import pytest
from batch_rename import BatchRename


class TestBatchRename:
    @pytest.fixture
    def batch_rename(self) -> BatchRename:
        return BatchRename()

    def test_empty_list_has_files_to_rename_test(self, batch_rename) -> None:
        assert not batch_rename.has_files_to_rename()

    def test_has_files_to_rename(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1])
        assert batch_rename.has_files_to_rename()

    def test_singular_get_log_msg(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1])
        assert batch_rename.get_log_message() == "S01E01"

    def test_multiples_get_log_msg(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1])
        batch_rename.append(2, 1, [2])
        assert batch_rename.get_log_message() == "S01E01, S01E02"

    def test_multi_episode_file_get_log_msg(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1, 2])
        assert batch_rename.get_log_message() == "S01E01-02"

    def test_multiple_multi_episode_file_get_log_msg(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1])
        batch_rename.append(2, 1, [2, 3])

        assert batch_rename.get_log_message() == "S01E01, S01E02-03"

    def test_singular_get_file_ids(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1])
        assert batch_rename.get_file_ids() == [1]

    def test_multiple_get_file_ids(self, batch_rename) -> None:
        batch_rename.append(1, 1, [1])
        batch_rename.append(2, 1, [2])
        assert batch_rename.get_file_ids() == [1, 2]
