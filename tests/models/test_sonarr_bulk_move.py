from pycliarr.api import SonarrSerieItem

from renamarr.sonarr.models.bulk_move import SonarrBulkMove


def make_series(series_id: int, title: str) -> SonarrSerieItem:
    return SonarrSerieItem(id=series_id, title=title)


def test_add_creates_move_and_reports_pending() -> None:
    bulk_move = SonarrBulkMove()
    series = make_series(10, "Show")

    bulk_move.add("/root", series)

    assert bulk_move.has_pending_moves() is True
    assert len(bulk_move.pending_moves) == 1
    move = bulk_move.pending_moves[0]
    assert move.rootFolderPath == "/root"
    assert move.series == [series]
    assert move.moveFiles is True


def test_add_appends_series_to_existing_move() -> None:
    bulk_move = SonarrBulkMove()
    series_a = make_series(10, "Show A")
    series_b = make_series(20, "Show B")
    bulk_move.add("/root", series_a)

    bulk_move.add("/root", series_b)

    assert len(bulk_move.pending_moves) == 1
    assert bulk_move.pending_moves[0].series == [series_a, series_b]


def test_get_log_message_returns_joined_series_titles() -> None:
    bulk_move = SonarrBulkMove()
    bulk_move.add("/root", make_series(1, "Show A"))
    bulk_move.add("/root", make_series(2, "Show B"))

    assert bulk_move.get_log_message(bulk_move.pending_moves[0]) == "Show A, Show B"


def test_get_log_message_uses_requested_move() -> None:
    bulk_move = SonarrBulkMove()
    bulk_move.add("/root", make_series(1, "Show A"))
    bulk_move.add("/other", make_series(2, "Show B"))

    assert bulk_move.get_log_message(bulk_move.pending_moves[1]) == "Show B"


def test_get_series_ids_returns_payload_ids() -> None:
    bulk_move = SonarrBulkMove()
    bulk_move.add("/root", make_series(1, "Show A"))
    bulk_move.add("/root", make_series(2, "Show B"))

    assert bulk_move.get_series_ids(bulk_move.pending_moves[0]) == [1, 2]


def test_add_creates_new_move_when_root_differs() -> None:
    bulk_move = SonarrBulkMove()
    bulk_move.add("/root", make_series(1, "Show A"))

    bulk_move.add("/other", make_series(2, "Show B"))

    assert len(bulk_move.pending_moves) == 2
    assert bulk_move.pending_moves[0].rootFolderPath == "/root"
    assert bulk_move.pending_moves[1].rootFolderPath == "/other"
