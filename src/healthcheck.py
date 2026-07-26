import json
import math
from collections.abc import Callable, Generator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic


_HEALTH_FILE = Path("/tmp/renamarr-health.json")
_HEARTBEAT_INTERVAL_SECONDS = 10.0
_MAX_HEARTBEAT_AGE_SECONDS = 30.0
_SCHEMA_VERSION = 1


class HealthState(StrEnum):
    """Application lifecycle states exposed to the container health check."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    RUNNING = "running"


class HealthReporter:
    """Publish atomic application heartbeat state for the container probe."""

    def __init__(
        self,
        path: Path = _HEALTH_FILE,
        clock: Callable[[], float] = monotonic,
        heartbeat_interval: float = _HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._path = path
        self._clock = clock
        self._heartbeat_interval = heartbeat_interval
        self._lock = Lock()
        self._state = HealthState.INITIALIZING
        self._last_heartbeat = float("-inf")
        self._write()

    def idle(self) -> None:
        """Record that the application is waiting for scheduled work."""
        self._state = HealthState.IDLE
        self._write()

    def heartbeat(self) -> None:
        """Refresh idle health when the configured interval has elapsed."""
        heartbeat = self._clock()
        if heartbeat - self._last_heartbeat >= self._heartbeat_interval:
            self._write(heartbeat)

    @contextmanager
    def running_job(self) -> Generator[None]:
        """Keep health fresh while a synchronous scheduled job is running."""
        self._state = HealthState.RUNNING
        self._write()
        stopped = Event()
        heartbeat_thread = Thread(
            target=self._heartbeat_until_stopped,
            args=(stopped,),
            daemon=True,
            name="renamarr-heartbeat",
        )
        heartbeat_thread.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat_thread.join()
            self.idle()

    def _heartbeat_until_stopped(self, stopped: Event) -> None:
        while not stopped.wait(self._heartbeat_interval):
            self._write()

    def _write(self, heartbeat: float | None = None) -> None:
        with self._lock:
            if heartbeat is None:
                heartbeat = self._clock()
            payload = {
                "version": _SCHEMA_VERSION,
                "state": self._state,
                "heartbeat": heartbeat,
            }
            temporary_path = self._path.with_name(f".{self._path.name}.tmp")
            temporary_path.write_text(
                json.dumps(payload, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary_path.replace(self._path)
            self._last_heartbeat = heartbeat


def check_health(
    path: Path = _HEALTH_FILE,
    clock: Callable[[], float] = monotonic,
    max_age: float = _MAX_HEARTBEAT_AGE_SECONDS,
) -> tuple[bool, str]:
    """Validate the application heartbeat and return a concise result."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return False, "heartbeat is unavailable"

    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "state",
        "heartbeat",
    }:
        return False, "heartbeat schema is invalid"
    if type(payload["version"]) is not int or payload["version"] != _SCHEMA_VERSION:
        return False, "heartbeat version is unsupported"
    try:
        HealthState(payload["state"])
    except TypeError, ValueError:
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
