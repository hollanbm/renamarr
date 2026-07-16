from loguru import logger
from schema import And, Optional, Schema, Use

from interval import Interval


NON_NEGATIVE_INTEGER = And(
    lambda value: type(value) is int,
    lambda value: value >= 0,
)

INTERVAL_SCHEMA = {
    Optional("days", default=0): NON_NEGATIVE_INTEGER,
    Optional("hours", default=0): NON_NEGATIVE_INTEGER,
    Optional("minutes", default=0): NON_NEGATIVE_INTEGER,
}

DEFAULT_INTERVAL = Interval(days=0, hours=1, minutes=0)
DEFAULT_SCHEDULE = {"enabled": True, "interval": DEFAULT_INTERVAL}


def _migrate_hourly_job(renamarr_config: object) -> object:
    """Map the deprecated hourly job option to the replacement schedule option.

    The deprecated field is retained for runtime warnings. Its value supplies
    ``schedule.enabled`` only when the replacement option is not explicitly set.
    """
    if not isinstance(renamarr_config, dict) or "hourly_job" not in renamarr_config:
        return renamarr_config

    logger.warning(
        "renamarr.hourly_job is deprecated; use renamarr.schedule.enabled instead. Alternatively, remove renamarr.hourly_job to use the default hourly schedule."
    )
    migrated_config = renamarr_config.copy()
    hourly_job = migrated_config["hourly_job"]
    schedule = migrated_config.get("schedule")
    if schedule is None:
        migrated_config["schedule"] = {"enabled": hourly_job}
    elif isinstance(schedule, dict) and "enabled" not in schedule:
        migrated_config["schedule"] = schedule | {"enabled": hourly_job}
    return migrated_config


SCHEDULE_SCHEMA = And(
    {
        Optional("enabled", default=True): bool,
        Optional("interval", default=DEFAULT_INTERVAL): And(
            dict,
            Use(lambda value: value or {"hours": 1}),
            INTERVAL_SCHEMA,
            Use(
                lambda value: Interval(
                    days=value["days"],
                    hours=value["hours"],
                    minutes=value["minutes"],
                )
            ),
        ),
    },
    lambda value: not value["enabled"] or value["interval"].total_minutes > 0,
    error="renamarr.schedule.interval must be greater than zero when scheduling is enabled",
)

CONFIG_SCHEMA = {
    Optional(
        "sonarr",
        default=[],
        ignore_extra_keys=True,
    ): And(
        lambda n: len(n),
        [
            {
                "name": And(
                    lambda s: s is not None,
                    Use(str),
                    lambda s: len(s) > 0,
                    error="sonarr[].name is a required field",
                ),
                "url": And(
                    lambda s: s is not None,
                    Use(str),
                    lambda s: len(s) > 0,
                    error="sonarr[].url is a required field",
                ),
                "api_key": And(
                    lambda s: s is not None,
                    Use(str),
                    lambda s: len(s) > 0,
                    error="sonarr[].api_key is a required field",
                ),
                Optional(
                    "series_scanner",
                    default=dict(
                        enabled=False,
                        hourly_job=False,
                        hours_before_air=4,
                    ),
                    ignore_extra_keys=True,
                ): {
                    Optional("enabled", default=False): bool,
                    Optional("hourly_job", default=False): bool,
                    Optional("hours_before_air", default=4): int,
                },
                Optional(
                    "renamarr",
                    default=dict(
                        enabled=False,
                        analyze_files=False,
                        rename_folders=False,
                        log_to_file=False,
                        schedule=DEFAULT_SCHEDULE,
                    ),
                    ignore_extra_keys=True,
                ): And(
                    Use(_migrate_hourly_job),
                    Schema(
                        {
                            Optional("enabled", default=False): bool,
                            Optional("hourly_job"): bool,
                            Optional("analyze_files", default=False): bool,
                            Optional("rename_folders", default=False): bool,
                            Optional("log_to_file", default=False): bool,
                            Optional(
                                "schedule", default=DEFAULT_SCHEDULE
                            ): SCHEDULE_SCHEMA,
                        },
                        ignore_extra_keys=True,
                    ),
                ),
            }
        ],
        ignore_extra_keys=True,
    ),
    Optional(
        "radarr",
        default=[],
        ignore_extra_keys=True,
    ): And(
        lambda n: len(n),
        [
            {
                "name": And(
                    lambda s: s is not None,
                    Use(str),
                    lambda s: len(s) > 0,
                    error="radarr[].name is a required field",
                ),
                "url": And(
                    lambda s: s is not None,
                    Use(str),
                    lambda s: len(s) > 0,
                    error="radarr[].url is a required field",
                ),
                "api_key": And(
                    lambda s: s is not None,
                    Use(str),
                    lambda s: len(s) > 0,
                    error="radarr[].api_key is a required field",
                ),
                Optional(
                    "renamarr",
                    default=dict(
                        enabled=False,
                        analyze_files=False,
                        rename_folders=False,
                        log_to_file=False,
                        schedule=DEFAULT_SCHEDULE,
                    ),
                    ignore_extra_keys=True,
                ): And(
                    Use(_migrate_hourly_job),
                    Schema(
                        {
                            Optional("enabled", default=False): bool,
                            Optional("hourly_job"): bool,
                            Optional("analyze_files", default=False): bool,
                            Optional("rename_folders", default=False): bool,
                            Optional("log_to_file", default=False): bool,
                            Optional(
                                "schedule", default=DEFAULT_SCHEDULE
                            ): SCHEDULE_SCHEMA,
                        },
                        ignore_extra_keys=True,
                    ),
                ),
            }
        ],
        ignore_extra_keys=True,
    ),
}
