from datetime import timedelta

import pytest

from iso8601 import parse_duration


class TestParseDuration:
    @pytest.mark.parametrize(
        ("duration_str", "expected"),
        [
            ("PT10M", timedelta(minutes=10)),
            ("PT1H", timedelta(hours=1)),
            ("PT1H30M", timedelta(hours=1, minutes=30)),
            ("PT2H45M30S", timedelta(hours=2, minutes=45, seconds=30)),
            ("PT30M", timedelta(minutes=30)),
            ("PT5S", timedelta(seconds=5)),
            ("P1D", timedelta(days=1)),
            ("P7D", timedelta(days=7)),
            ("P1DT12H", timedelta(days=1, hours=12)),
            ("P1DT12H30M", timedelta(days=1, hours=12, minutes=30)),
            ("P1DT12H30M10S", timedelta(days=1, hours=12, minutes=30, seconds=10)),
            ("PT0S", timedelta()),
            ("P0D", timedelta()),
        ],
    )
    def test_valid_durations(self, duration_str: str, expected: timedelta) -> None:
        assert parse_duration(duration_str) == expected

    @pytest.mark.parametrize(
        "duration_str",
        [
            "",
            "P",
            "PT",
            "10M",
            "P10M",
            "PT10",
            "PTM",
            "T10M",
            "P1DT",
            "P1YT10M",
            "P1MT10M",
            "P1W",
            "hello",
            "P T10M",
        ],
    )
    def test_invalid_durations_raise_value_error(self, duration_str: str) -> None:
        with pytest.raises(ValueError):
            parse_duration(duration_str)

    def test_p_only_with_no_components_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one component"):
            parse_duration("P")

    def test_pt_only_with_no_components_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one component"):
            parse_duration("PT")

    def test_regex_pattern_defines_days_hours_minutes_seconds(self) -> None:
        from iso8601 import _ISO8601_DURATION_RE

        match = _ISO8601_DURATION_RE.match("P10DT5H3M45S")
        assert match is not None
        assert match.group("days") == "10"
        assert match.group("hours") == "5"
        assert match.group("minutes") == "3"
        assert match.group("seconds") == "45"

    def test_every_valid_duration_roundtrips_with_total_seconds(
        self,
    ) -> None:
        durations = [
            "PT5M",
            "PT10M",
            "PT1H",
            "PT6H",
            "P1D",
            "P7D",
            "PT1H30M",
            "PT2H45M30S",
        ]
        for d in durations:
            td = parse_duration(d)
            assert td.total_seconds() >= 0