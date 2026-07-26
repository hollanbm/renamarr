import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

from renamarr.healthcheck.health_state import HealthState
from renamarr.healthcheck.settings import (
    HEALTH_FILE,
    HEARTBEAT_INTERVAL_SECONDS,
    SCHEMA_VERSION,
)


class HealthReporter:
    """Publish atomic application heartbeat state for the container probe."""

    def __init__(
        self,
        path: Path = HEALTH_FILE,
        clock: Callable[[], float] = monotonic,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
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
                "version": SCHEMA_VERSION,
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
