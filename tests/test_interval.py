from interval import Interval


def test_total_minutes() -> None:
    assert Interval(days=2, hours=3, minutes=4).total_minutes == 3064
