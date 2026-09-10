# Local Setup

## Requirements

- [mise 2026.8.2 or newer](https://mise.jdx.dev/)
- A Docker-compatible runtime for building the container image (optional)
- Dependency locking is configured for macOS and Linux environments only

You will need to create `config.yml` in the [config](../config/) folder in the root of the repo.

```shell
mise install

mise run sync

mise run check

mise run audit

mise run docker-build

uv run python src/main.py
```

## python-dotenv

renamarr automatically loads `.env.local` file at startup when one is present.

The following variables are set in the included `.env.local`.

| Variable        | Value      | Purpose                                                                      |
| --------------- | ---------- | ---------------------------------------------------------------------------- |
| `CONFIG_DIR`    | `./config` | Uses the repo-local `config/` directory so local `config.yml` is discovered. |
| `LOG_LEVEL`     | `DEBUG`    | Enables verbose local logging.                                               |
| `LOG_DIR`       | `./logs`   | Writes local log files to the repo-local `logs/` directory.                  |
| `LOG_ROTATION`  | `00:00`    | Rotates log files daily at midnight.                                         |
| `LOG_RETENTION` | `7 days`   | Retains rotated log files for seven days.                                    |

## Logging and OTLP

`.env.local` is loaded before logging is configured. Shell environment variables take precedence over values in that file.

The default `LOG_FORMAT=text` gives readable stdout and instance files; stdout uses colors only in an interactive terminal. To inspect the structured JSON events locally:

```shell
LOG_FORMAT=json uv run python src/main.py
```

JSON output contains one object per line. Run summaries expose numeric outcome counts, and scoped context adds `arr_type`, `instance`, and `item` where available. `arr_type` is `sonarr` or `radarr`, and `instance` is its configured name. The separate OTLP resource attribute `service.name` identifies Renamarr and defaults to `renamarr`. `LOG_LEVEL` accepts standard levels without regard to case, and `DEBUG` includes source locations. Tracebacks exclude local variables.

For file logging, enable an instance's `renamarr.log_to_file` option. `LOG_ROTATION` accepts daily local-time `HH:MM`; `LOG_RETENTION` accepts positive whole-day values such as `1 day` or `7 days`. Rotation and age-based cleanup happen on the next emitted record after the boundary, including cleanup of legacy Loguru archives. If the file cannot be opened, Renamarr warns on stdout and continues.

To export logs to an existing Alloy or OpenTelemetry Collector HTTP receiver on your machine:

```shell
OTEL_LOGS_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
uv run python src/main.py
```

The base endpoint becomes `http://localhost:4318/v1/logs`. Use `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` for a complete logs URL. Export is disabled by default and supports only `http/protobuf`; `OTEL_SDK_DISABLED=true` disables it explicitly. `OTEL_SERVICE_NAME` defaults to `renamarr`. See [OpenTelemetry Logs](../README.md#opentelemetry-logs) for resource, authentication, TLS, timeout, and batch settings.

Stdout remains available during OTLP export. Collect only one of those routes into the same backend. Normal exit and SIGINT/SIGTERM drain pending logs; Compose examples allow 35 seconds for shutdown. Tracing and metrics instrumentation are not enabled by these settings.

## direnv

```shell
direnv allow
```

The included `.envrc` sets:

| Variable      | Value                   | Purpose                                                                           |
| ------------- | ----------------------- | --------------------------------------------------------------------------------- |
| `BRANCH_NAME` | current git branch name | used for image tag when building with [docker-compose.yml](../docker-compose.yml) |
