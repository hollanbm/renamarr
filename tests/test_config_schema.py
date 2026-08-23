from unittest.mock import MagicMock

import pytest
from schema import Schema, SchemaError

from config_schema import CONFIG_SCHEMA
from interval import Interval
from renamarr.models.command import CommandPollingSettings


def validate_config(config: dict[str, object]) -> dict[str, object]:
    return Schema(CONFIG_SCHEMA).validate(config)


def minimal_instance_config() -> dict[str, str]:
    return {
        "name": "instance",
        "url": "https://instance.tld",
        "api_key": "api-key",
    }


def _renamarr_config(validated: dict[str, object], service: str) -> dict[str, object]:
    service_configs = validated[service]
    assert isinstance(service_configs, list)
    instance_config = service_configs[0]
    assert isinstance(instance_config, dict)
    renamarr_config = instance_config["renamarr"]
    assert isinstance(renamarr_config, dict)
    return renamarr_config


def test_omitted_services_default_to_empty_lists() -> None:
    assert validate_config({}) == {"sonarr": [], "radarr": []}


def test_minimal_sonarr_config_receives_defaults() -> None:
    validated = validate_config({"sonarr": [minimal_instance_config()]})

    assert validated["radarr"] == []
    assert validated["sonarr"] == [
        {
            "name": "instance",
            "url": "https://instance.tld",
            "api_key": "api-key",
            "renamarr": {
                "enabled": False,
                "analyze_files": False,
                "rename_folders": False,
                "log_to_file": False,
                "schedule": {
                    "enabled": True,
                    "interval": Interval(days=0, hours=1, minutes=0),
                },
                "command_polling": CommandPollingSettings(),
            },
        }
    ]


def test_minimal_radarr_config_receives_defaults() -> None:
    validated = validate_config({"radarr": [minimal_instance_config()]})

    assert validated["sonarr"] == []
    assert validated["radarr"] == [
        {
            "name": "instance",
            "url": "https://instance.tld",
            "api_key": "api-key",
            "renamarr": {
                "enabled": False,
                "analyze_files": False,
                "rename_folders": False,
                "log_to_file": False,
                "schedule": {
                    "enabled": True,
                    "interval": Interval(days=0, hours=1, minutes=0),
                },
                "command_polling": CommandPollingSettings(),
            },
        }
    ]


def test_omitted_renamarr_defaults_are_independent_between_services() -> None:
    validated = validate_config(
        {
            "sonarr": [minimal_instance_config()],
            "radarr": [minimal_instance_config()],
        }
    )
    sonarr_renamarr = _renamarr_config(validated, "sonarr")
    radarr_renamarr = _renamarr_config(validated, "radarr")
    sonarr_schedule = sonarr_renamarr["schedule"]
    radarr_schedule = radarr_renamarr["schedule"]
    assert isinstance(sonarr_schedule, dict)
    assert isinstance(radarr_schedule, dict)

    sonarr_renamarr["enabled"] = True
    sonarr_schedule["enabled"] = False

    assert radarr_renamarr["enabled"] is False
    assert radarr_schedule["enabled"] is True


def test_partial_renamarr_schedule_defaults_are_independent_between_instances() -> None:
    validated = validate_config(
        {
            "sonarr": [
                minimal_instance_config() | {"renamarr": {"enabled": True}},
                minimal_instance_config() | {"renamarr": {"analyze_files": True}},
            ]
        }
    )
    first_schedule = validated["sonarr"][0]["renamarr"]["schedule"]
    second_schedule = validated["sonarr"][1]["renamarr"]["schedule"]

    assert first_schedule is not second_schedule
    first_schedule["enabled"] = False
    assert second_schedule["enabled"] is True


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_present_empty_service_list_is_rejected(service: str) -> None:
    with pytest.raises(SchemaError):
        validate_config({service: []})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize("field", ["name", "url", "api_key"])
def test_required_service_fields_reject_missing_values(
    service: str, field: str
) -> None:
    instance_config = minimal_instance_config()
    del instance_config[field]

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize("field", ["name", "url", "api_key"])
def test_required_service_fields_reject_empty_values(service: str, field: str) -> None:
    instance_config = minimal_instance_config() | {field: ""}

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})


def test_extra_service_and_nested_keys_are_ignored() -> None:
    validated = validate_config(
        {
            "sonarr": [
                minimal_instance_config()
                | {
                    "unexpected": True,
                    "renamarr": {
                        "rename_folders": True,
                        "unexpected": True,
                    },
                }
            ],
            "radarr": [
                minimal_instance_config()
                | {
                    "unexpected": True,
                    "renamarr": {
                        "analyze_files": True,
                        "unexpected": True,
                    },
                }
            ],
        }
    )

    sonarr_config = validated["sonarr"][0]
    radarr_config = validated["radarr"][0]

    assert "unexpected" not in sonarr_config
    assert "unexpected" not in sonarr_config["renamarr"]
    assert "unexpected" not in radarr_config
    assert "unexpected" not in radarr_config["renamarr"]
    assert sonarr_config["renamarr"]["rename_folders"] is True
    assert radarr_config["renamarr"]["analyze_files"] is True


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    "renamarr_config",
    [
        pytest.param({"enabled": "true"}, id="enabled"),
        pytest.param({"analyze_files": "true"}, id="analyze-files"),
        pytest.param({"rename_folders": "true"}, id="rename-folders"),
        pytest.param({"log_to_file": "true"}, id="log-to-file"),
        pytest.param(
            {"hourly_job": "true", "schedule": {"enabled": False}},
            id="deprecated-hourly-job",
        ),
        pytest.param(
            {"schedule": {"enabled": "true"}},
            id="schedule-enabled",
        ),
    ],
)
def test_boolean_fields_reject_non_bool_values(
    service: str, renamarr_config: dict[str, object]
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": renamarr_config
    }

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ({}, Interval(days=0, hours=1, minutes=0)),
        ({"minutes": 30}, Interval(days=0, hours=0, minutes=30)),
        ({"days": 2}, Interval(days=2, hours=0, minutes=0)),
        ({"days": 30}, Interval(days=30, hours=0, minutes=0)),
        ({"hours": 3}, Interval(days=0, hours=3, minutes=0)),
        ({"days": 2, "hours": 3, "minutes": 4}, Interval(2, 3, 4)),
        ({"days": 0, "hours": 0, "minutes": 5}, Interval(0, 0, 5)),
    ],
)
def test_schedule_interval_is_validated(
    service: str, configured: dict[str, int], expected: Interval
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"schedule": {"interval": configured}}
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["schedule"] == {
        "enabled": True,
        "interval": expected,
    }


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_disabled_schedule_accepts_zero_interval(service: str) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "schedule": {
                "enabled": False,
                "interval": {"days": 0, "hours": 0, "minutes": 0},
            }
        }
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["schedule"]["interval"] == Interval(
        0, 0, 0
    )


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize("hourly_job", [True, False])
def test_deprecated_hourly_job_sets_schedule_enabled_without_parse_warning(
    service: str, hourly_job: bool, mock_loguru_warning: MagicMock
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"hourly_job": hourly_job}
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["hourly_job"] is hourly_job
    assert validated[service][0]["renamarr"]["schedule"]["enabled"] is hourly_job
    mock_loguru_warning.assert_not_called()


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_deprecated_hourly_job_sets_enabled_on_custom_schedule(
    service: str,
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "hourly_job": False,
            "schedule": {"interval": {"minutes": 30}},
        }
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["schedule"] == {
        "enabled": False,
        "interval": Interval(days=0, hours=0, minutes=30),
    }


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    ("hourly_job", "schedule_enabled"),
    [(False, True), (True, False)],
)
def test_schedule_enabled_takes_precedence_over_deprecated_hourly_job(
    service: str, hourly_job: bool, schedule_enabled: bool
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "hourly_job": hourly_job,
            "schedule": {"enabled": schedule_enabled},
        }
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["schedule"]["enabled"] is schedule_enabled


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize("schedule", [None, "hourly"])
def test_deprecated_hourly_job_does_not_hide_invalid_schedule(
    service: str, schedule: object
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"hourly_job": True, "schedule": schedule}
    }

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    "interval",
    [
        {"days": 31},
        {"hours": 721},
        {"minutes": 43201},
        {"days": 30, "minutes": 1},
    ],
)
def test_schedule_rejects_intervals_over_thirty_days(
    service: str, interval: dict[str, int]
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"schedule": {"interval": interval}}
    }

    with pytest.raises(
        SchemaError,
        match="renamarr.schedule.interval must not exceed 30 days",
    ):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_enabled_schedule_rejects_zero_interval(service: str) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "schedule": {
                "enabled": True,
                "interval": {"days": 0, "hours": 0, "minutes": 0},
            }
        }
    }

    with pytest.raises(
        SchemaError,
        match=(
            "renamarr.schedule.interval must be greater than zero when scheduling "
            "is enabled"
        ),
    ):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("days", -1, id="negative"),
        pytest.param("hours", True, id="boolean"),
        pytest.param("minutes", 1.5, id="non-integer"),
    ],
)
def test_schedule_rejects_invalid_interval_components_when_disabled(
    service: str, field: str, value: object
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "schedule": {
                "enabled": False,
                "interval": {field: value},
            }
        }
    }

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_omitted_command_polling_receives_defaults(service: str) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"enabled": True}
    }

    validated = validate_config({service: [instance_config]})
    renamarr_config = _renamarr_config(validated, service)

    assert renamarr_config["command_polling"] == (
        CommandPollingSettings(timeout_seconds=120, check_interval_seconds=3)
    )


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (
            {},
            CommandPollingSettings(timeout_seconds=120, check_interval_seconds=3),
        ),
        (
            {"timeout_seconds": 60},
            CommandPollingSettings(timeout_seconds=60, check_interval_seconds=3),
        ),
        (
            {"check_interval_seconds": 5},
            CommandPollingSettings(timeout_seconds=120, check_interval_seconds=5),
        ),
        (
            {"timeout_seconds": 120, "check_interval_seconds": 30},
            CommandPollingSettings(timeout_seconds=120, check_interval_seconds=30),
        ),
        (
            {"timeout_seconds": 10, "check_interval_seconds": 10},
            CommandPollingSettings(timeout_seconds=10, check_interval_seconds=10),
        ),
    ],
)
def test_command_polling_is_validated(
    service: str,
    configured: dict[str, int],
    expected: CommandPollingSettings,
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"command_polling": configured}
    }

    validated = validate_config({service: [instance_config]})
    renamarr_config = _renamarr_config(validated, service)

    assert renamarr_config["command_polling"] == expected


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize("field", ["timeout_seconds", "check_interval_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "1"])
def test_command_polling_rejects_invalid_integer_values(
    service: str, field: str, value: object
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"command_polling": {field: value}}
    }

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_command_polling_rejects_check_interval_over_timeout(service: str) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "command_polling": {
                "timeout_seconds": 10,
                "check_interval_seconds": 11,
            }
        }
    }

    with pytest.raises(
        SchemaError,
        match=(
            "renamarr.command_polling.check_interval_seconds must not exceed "
            "timeout_seconds"
        ),
    ):
        validate_config({service: [instance_config]})
