from typing import TypedDict

import pytest

from renamarr.models.command import CommandPollingSettings


class _CommandPollingSettingsInput(TypedDict, total=False):
    timeout_seconds: int
    check_interval_seconds: int


@pytest.mark.parametrize(
    ("settings", "expected_message"),
    [
        pytest.param(
            {"timeout_seconds": True, "check_interval_seconds": 1},
            "^timeout_seconds must be a positive integer$",
            id="boolean-timeout",
        ),
        pytest.param(
            {"timeout_seconds": 0},
            "^timeout_seconds must be a positive integer$",
            id="non-positive-timeout",
        ),
        pytest.param(
            {"check_interval_seconds": True},
            "^check_interval_seconds must be a positive integer$",
            id="boolean-check-interval",
        ),
        pytest.param(
            {"check_interval_seconds": -1},
            "^check_interval_seconds must be a positive integer$",
            id="non-positive-check-interval",
        ),
        pytest.param(
            {"timeout_seconds": 10, "check_interval_seconds": 11},
            "^check_interval_seconds must not exceed timeout_seconds$",
            id="check-exceeds-timeout",
        ),
    ],
)
def test_command_polling_settings_reject_invalid_values(
    settings: _CommandPollingSettingsInput,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        CommandPollingSettings(**settings)


def test_command_polling_settings_accept_valid_boundary() -> None:
    assert CommandPollingSettings(10, 10) == CommandPollingSettings(
        timeout_seconds=10,
        check_interval_seconds=10,
    )
