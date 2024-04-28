from schema import Use, And, Optional

CONFIG_SCHEMA = {
    "sonarr": And(
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
                "series_scanner": {
                    "enabled": bool,
                    "hourly_job": bool,
                    Optional("hours_before_air", default=4): int,
                },
                "tba_renamer": {"enabled": bool, "hourly_job": bool},
            }
        ],
    ),
}
