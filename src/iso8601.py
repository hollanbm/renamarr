import re
from datetime import timedelta

_ISO8601_DURATION_RE = re.compile(
    r"^P((?P<days>\d+)D)?(T((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?)?$"
)


def parse_duration(duration_str: str) -> timedelta:
    match = _ISO8601_DURATION_RE.match(duration_str)
    if not match:
        raise ValueError(f"Invalid ISO 8601 duration: {duration_str!r}")
    groups = match.groupdict()
    if not any(groups[part] for part in ("days", "hours", "minutes", "seconds")):
        raise ValueError(
            f"ISO 8601 duration must include at least one component: {duration_str!r}"
        )
    return timedelta(
        days=int(groups["days"] or 0),
        hours=int(groups["hours"] or 0),
        minutes=int(groups["minutes"] or 0),
        seconds=int(groups["seconds"] or 0),
    )