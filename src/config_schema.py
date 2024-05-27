from schema import And, Optional, Use

CONFIG_SCHEMA = {
    Optional(
        "sonarr",
        default=dict(
            name="",
            url="",
            api_key="",
            series_scanner=dict(enabled=False, hourly_job=False, hours_before_air=4),
            existing_renamer=dict(enabled=False, hourly_job=False, analyze_files=False),
            renamarr=dict(enabled=False, hourly_job=False, analyze_files=False),
        ),
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
                # keeping for backwards compatibility between v1.0 and v0.5
                Optional(
                    "existing_renamer",
                    default=dict(enabled=False, hourly_job=False, analyze_files=False),
                    ignore_extra_keys=True,
                ): {
                    Optional("enabled", default=False): bool,
                    Optional("hourly_job", default=False): bool,
                    Optional("analyze_files", default=False): bool,
                },
                Optional(
                    "renamarr",
                    default=dict(enabled=False, hourly_job=False, analyze_files=False),
                    ignore_extra_keys=True,
                ): {
                    Optional("enabled", default=False): bool,
                    Optional("hourly_job", default=False): bool,
                    Optional("analyze_files", default=False): bool,
                },
            }
        ],
        ignore_extra_keys=True,
    ),
    Optional(
        "radarr",
        default=dict(
            name="",
            url="",
            api_key="",
            renamarr=dict(enabled=False, hourly_job=False, analyze_files=False),
        ),
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
                    default=dict(enabled=False, hourly_job=False, analyze_files=False),
                    ignore_extra_keys=True,
                ): {
                    Optional("enabled", default=False): bool,
                    Optional("hourly_job", default=False): bool,
                    Optional("analyze_files", default=False): bool,
                },
            }
        ],
        ignore_extra_keys=True,
    ),
}
