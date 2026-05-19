from models.radarr_bulk_move import RadarrBulkMove


def test_add_creates_move_and_reports_pending() -> None:
    bulk_move = RadarrBulkMove()

    bulk_move.add("/root", 10)

    assert bulk_move.has_pending_moves() is True
    assert len(bulk_move.pending_moves) == 1
    move = bulk_move.pending_moves[0]
    assert move.rootFolderPath == "/root"
    assert move.movieIds == [10]
    assert move.moveFiles is True


def test_add_appends_movie_id_to_existing_move() -> None:
    bulk_move = RadarrBulkMove()
    bulk_move.add("/root", 10)

    bulk_move.add("/root", 20)

    assert len(bulk_move.pending_moves) == 1
    assert bulk_move.pending_moves[0].movieIds == [10, 20]


def test_add_creates_new_move_when_root_differs() -> None:
    bulk_move = RadarrBulkMove()
    bulk_move.add("/root", 1)

    bulk_move.add("/other", 2)

    assert len(bulk_move.pending_moves) == 2
    assert bulk_move.pending_moves[0].rootFolderPath == "/root"
    assert bulk_move.pending_moves[1].rootFolderPath == "/other"
