from pathlib import Path

# Shared by the application and Docker health probe on an isolated tmpfs.
HEALTH_FILE = Path("/tmp/renamarr-health.json")  # noqa: S108
HEARTBEAT_INTERVAL_SECONDS = 10.0
MAX_HEARTBEAT_AGE_SECONDS = 30.0
SCHEMA_VERSION = 1
