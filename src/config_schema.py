from schema import And, Optional, Use

from interval import Interval


NON_NEGATIVE_INTEGER = And(
    lambda value: type(value) is int,
    lambda value: value >= 0,
)

INTERVAL_SCHEMA = {
    Optional("days", default=0): NON_NEGATIVE_INTEGER,
    Optional("hours", default=1): NON_NEGATIVE_INTEGER,
    Optional("minutes", default=0): NON_NEGATIVE_INTEGER,
}

DEFAULT_INTERVAL = Interval(days=0, hours=1, minutes=0)
DEFAULT_SCHEDULE = {"enabled": True, "interval": DEFAULT_INTERVAL}

SCHEDULE_SCHEMA = And(
    {
        Optional("enabled", default=True): bool,
        Optional("interval", default=DEFAULT_INTERVAL): And(
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
                ): {
                    Optional("enabled", default=False): bool,
                    Optional("analyze_files", default=False): bool,
                    Optional("rename_folders", default=False): bool,
                    Optional("log_to_file", default=False): bool,
                    Optional("schedule", default=DEFAULT_SCHEDULE): SCHEDULE_SCHEMA,
                },
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
                ): {
                    Optional("enabled", default=False): bool,
                    Optional("analyze_files", default=False): bool,
                    Optional("rename_folders", default=False): bool,
                    Optional("log_to_file", default=False): bool,
                    Optional("schedule", default=DEFAULT_SCHEDULE): SCHEDULE_SCHEMA,
                },
            }
        ],
        ignore_extra_keys=True,
    ),
}
