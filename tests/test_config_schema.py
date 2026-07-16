import pytest
from schema import Schema, SchemaError

from config_schema import CONFIG_SCHEMA
from interval import Interval


def validate_config(config: dict[str, object]) -> dict[str, object]:
    return Schema(CONFIG_SCHEMA).validate(config)


def minimal_instance_config() -> dict[str, str]:
    return {
        "name": "instance",
        "url": "https://instance.tld",
        "api_key": "api-key",
    }


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
            "series_scanner": {
                "enabled": False,
                "hourly_job": False,
                "hours_before_air": 4,
            },
            "renamarr": {
                "enabled": False,
                "analyze_files": False,
                "rename_folders": False,
                "log_to_file": False,
                "schedule": {
                    "enabled": True,
                    "interval": Interval(days=0, hours=1, minutes=0),
                },
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
            },
        }
    ]


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
                    "series_scanner": {
                        "enabled": True,
                        "unexpected": True,
                    },
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
    assert "unexpected" not in sonarr_config["series_scanner"]
    assert "unexpected" not in sonarr_config["renamarr"]
    assert "unexpected" not in radarr_config
    assert "unexpected" not in radarr_config["renamarr"]
    assert sonarr_config["series_scanner"]["enabled"] is True
    assert sonarr_config["renamarr"]["rename_folders"] is True
    assert radarr_config["renamarr"]["analyze_files"] is True


@pytest.mark.parametrize(
    ("service", "section", "field"),
    [
        ("sonarr", "series_scanner", "enabled"),
        ("sonarr", "series_scanner", "hourly_job"),
        ("sonarr", "renamarr", "enabled"),
        ("sonarr", "renamarr", "analyze_files"),
        ("sonarr", "renamarr", "rename_folders"),
        ("sonarr", "renamarr", "log_to_file"),
        ("radarr", "renamarr", "enabled"),
        ("radarr", "renamarr", "analyze_files"),
        ("radarr", "renamarr", "rename_folders"),
        ("radarr", "renamarr", "log_to_file"),
    ],
)
def test_boolean_fields_reject_non_bool_values(
    service: str, section: str, field: str
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        section: {field: "true"}
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
def test_deprecated_hourly_job_sets_schedule_enabled(
    service: str, hourly_job: bool, mock_loguru_warning
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"hourly_job": hourly_job}
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["hourly_job"] is hourly_job
    assert validated[service][0]["renamarr"]["schedule"]["enabled"] is hourly_job
    mock_loguru_warning.assert_called_once_with(
        "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. Alternatively, remove renamarr.hourly_job to use the default hourly schedule."
    )


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_deprecated_hourly_job_sets_enabled_on_custom_schedule(
    service: str, mock_loguru_warning
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
    mock_loguru_warning.assert_called_once_with(
        "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. Alternatively, remove renamarr.hourly_job to use the default hourly schedule."
    )


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_schedule_enabled_takes_precedence_over_deprecated_hourly_job(
    service: str, mock_loguru_warning
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {
            "hourly_job": False,
            "schedule": {"enabled": True},
        }
    }

    validated = validate_config({service: [instance_config]})

    assert validated[service][0]["renamarr"]["schedule"]["enabled"] is True
    mock_loguru_warning.assert_called_once_with(
        "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. Alternatively, remove renamarr.hourly_job to use the default hourly schedule."
    )


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
def test_deprecated_hourly_job_does_not_hide_invalid_schedule(
    service: str, mock_loguru_warning
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"hourly_job": True, "schedule": "hourly"}
    }

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})

    mock_loguru_warning.assert_called_once_with(
        "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. Alternatively, remove renamarr.hourly_job to use the default hourly schedule."
    )


@pytest.mark.parametrize("service", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    "interval",
    [
        {"days": 0, "hours": 0, "minutes": 0},
        {"days": -1},
        {"hours": True},
        {"minutes": 1.5},
    ],
)
def test_enabled_schedule_rejects_invalid_interval(
    service: str, interval: dict[str, object]
) -> None:
    instance_config: dict[str, object] = minimal_instance_config() | {
        "renamarr": {"schedule": {"enabled": True, "interval": interval}}
    }

    with pytest.raises(SchemaError):
        validate_config({service: [instance_config]})
