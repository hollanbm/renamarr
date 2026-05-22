import pytest
from schema import Schema, SchemaError

from config_schema import CONFIG_SCHEMA


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
                "hourly_job": False,
                "analyze_files": False,
                "rename_folders": False,
                "log_to_file": False,
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
                "hourly_job": False,
                "analyze_files": False,
                "rename_folders": False,
                "log_to_file": False,
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
        ("sonarr", "renamarr", "hourly_job"),
        ("sonarr", "renamarr", "analyze_files"),
        ("sonarr", "renamarr", "rename_folders"),
        ("sonarr", "renamarr", "log_to_file"),
        ("radarr", "renamarr", "enabled"),
        ("radarr", "renamarr", "hourly_job"),
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
