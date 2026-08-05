import json
import math
from json import JSONDecodeError
from time import monotonic
from typing import TYPE_CHECKING

from renamarr.healthcheck.health_state import HealthState
from renamarr.healthcheck.settings import (
    HEALTH_FILE,
    MAX_HEARTBEAT_AGE_SECONDS,
    SCHEMA_VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def check_health(
    path: Path = HEALTH_FILE,
    clock: Callable[[], float] = monotonic,
    max_age: float = MAX_HEARTBEAT_AGE_SECONDS,
) -> tuple[bool, str]:
    """Validate the application heartbeat and return a concise result."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (
        OSError,
        UnicodeError,
        JSONDecodeError,
    ):
        return False, "heartbeat is unavailable"

    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "state",
        "heartbeat",
    }:
        return False, "heartbeat schema is invalid"
    if type(payload["version"]) is not int or payload["version"] != SCHEMA_VERSION:
        return False, "heartbeat version is unsupported"
    try:
        HealthState(payload["state"])
    except (
        TypeError,
        ValueError,
    ):
        return False, "heartbeat state is invalid"

    heartbeat = payload["heartbeat"]
    if (
        isinstance(heartbeat, bool)
        or not isinstance(heartbeat, int | float)
        or not math.isfinite(heartbeat)
    ):
        return False, "heartbeat timestamp is invalid"
    age = clock() - heartbeat
    if age < 0 or age > max_age:
        return False, "heartbeat is stale"
    return True, "healthy"


def main() -> int:
    """Run the container health probe."""
    healthy, message = check_health()
    if not healthy:
        print(message)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
