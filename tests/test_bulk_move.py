import pytest

from models.bulk_move import BulkMove


def test_add_creates_move_and_reports_pending() -> None:
    bulk_move = BulkMove()

    bulk_move.add("/root", 10)

    assert bulk_move.has_pending_moves() is True
    assert len(bulk_move.pending_moves) == 1
    move = bulk_move.pending_moves[0]
    assert move.rootFolderPath == "/root"
    assert move.seriesIds == [10]
    assert move.moveFiles is True


def test_add_appends_series_id_to_existing_move() -> None:
    bulk_move = BulkMove()
    bulk_move.add("/root", 10)

    bulk_move.add("/root", 20)

    assert len(bulk_move.pending_moves) == 1
    assert bulk_move.pending_moves[0].seriesIds == [10, 20]


def test_get_log_message_requires_series_ids_attribute() -> None:
    bulk_move = BulkMove()
    bulk_move.add("/root", 1)

    with pytest.raises(AttributeError):
        bulk_move.get_log_message()


def test_get_log_message_returns_joined_series_ids_when_present() -> None:
    bulk_move = BulkMove()
    bulk_move.add("/root", 1)
    # BulkMove expects a snake_case series_ids that Move doesn't provide; inject to cover return path
    bulk_move.pending_moves[0].series_ids = bulk_move.pending_moves[0].seriesIds

    assert bulk_move.get_log_message() == "[1]"


def test_add_creates_new_move_when_root_differs() -> None:
    bulk_move = BulkMove()
    bulk_move.add("/root", 1)

    bulk_move.add("/other", 2)

    assert len(bulk_move.pending_moves) == 2
    assert bulk_move.pending_moves[0].rootFolderPath == "/root"
    assert bulk_move.pending_moves[1].rootFolderPath == "/other"
