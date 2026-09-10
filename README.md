# Renamarr

[![codecov](https://codecov.io/gh/hollanbm/renamarr/graph/badge.svg?token=8MJ61PXR4V)](https://codecov.io/gh/hollanbm/renamarr)

## Quick Start

### Docker

#### Recurring job

This is the default deployment mode. Enabled Renamarr jobs run immediately, repeat every hour unless configured otherwise, and the container remains running with `restart: unless-stopped`.

1. Copy/Rename [config.yml.example](example/config.yml.example) to `config.yml`
2. Update `config.yml` as needed.
   - See [Configuration](#configuration) for further explanation
3. Bring up app using provided [docker-compose.yml](example/docker-compose.yml)

#### External scheduler

Each invocation runs every enabled job once and exits without restarting when no recurring jobs are configured.

1. Copy/Rename [config.yml.example](example/external-scheduler/config.yml.example) to `config.yml`
2. Update `config.yml` as needed
   - _Set `sonarr[].renamarr.schedule.enabled` to `false` for every enabled Renamarr instance._
   - _Set `radarr[].renamarr.schedule.enabled` to `false` for every enabled Renamarr instance._
3. Invoke the app from your scheduler using the provided [docker-compose.yml](example/external-scheduler/docker-compose.yml)

#### Troubleshooting

Image tags ending in `-dev` can be used for troubleshooting purposes, but are not intended for normal usage. Pre-release images are tagged with their specific release version and do not change or overwrite the `latest` or `latest-dev` tags.

## How it works

### Renamarr

This job uses the [Sonarr API](https://sonarr.tv/docs/api/)/[Radarr API](https://radarr.video/docs/api/) to do the following

Sonarr API access uses [devopsarr/sonarr-py](https://github.com/devopsarr/sonarr-py), and Radarr API access uses [devopsarr/radarr-py](https://github.com/devopsarr/radarr-py). Existing Sonarr and Radarr configuration remains unchanged.

- Iterate over all items (Movies or Series)
  - Checks if any items need to be renamed
    - Radarr [get_api_v3_rename](https://radarr.video/docs/api/#/RenameMovie/get_api_v3_rename)
    - Sonarr [get_api_v3_rename](https://sonarr.tv/docs/api/#/RenameEpisode/get_api_v3_rename)
  - Triggers a rename on any item that need be renamed
    - Series renames are batched up, for one rename call per series
    - Movie renames are discovered per movie, then initiated in one batch command with all movie IDs that need a rename

#### Analyze Files

This config option is useful if you have audio/video codec information as part of your mediaformat, and you are transcoding files after import. This will initiate a rescan of the files in your library, so that the mediainfo will be updated. Then renamarr will come through and detect changes, and rename the files

#### Rename Folders

This config option will rename series or movie folders when they no longer match your configured MediaFormat.

- uses [/api/v3/series/{id}/folder](https://sonarr.tv/docs/api/#/SeriesFolder/get_api_v3_series__id__folder) endpoint to determine if the series folder requires an update
- uses [/api/v3/series/editor](https://sonarr.tv/docs/api/#v3/tag/serieseditor/PUT/api/v3/series/editor) endpoint to update series rootFolderPath to it's current value
  - moving the folder in place
- uses [/api/v3/movie/{id}/folder](https://radarr.video/docs/api/#/MovieFolder/get_api_v3_movie__id__folder) endpoint to determine if the movie folder requires an update
- uses [/api/v3/movie/editor](https://radarr.video/docs/api/#/MovieEditor/put_api_v3_movie_editor) endpoint to update movie rootFolderPath to it's current value
  - moving the folder in place
- sends a Sonarr `RescanSeries` command to rescan series after successful folder moves
- sends a Radarr `RefreshMovie` command to rescan movies after successful folder moves
- Series and movies are processed in bulk at the end of the run, **per root folder**

#### Command Polling and Partial Results

Analysis, file rename, and post-move rescan commands use the same polling settings. Renamarr checks each command immediately, then checks every `command_polling.check_interval_seconds` until it succeeds, reports a completed failure, encounters a status-check error, or reaches `command_polling.timeout_seconds`. The timeout applies separately to each asynchronous command; it is not an HTTP request or whole-scan timeout.

### Usage

The application runs enabled jobs immediately on startup. Renamarr jobs repeat every hour by default. Set `renamarr.schedule.enabled` to `false` to run once, or configure the interval in days, hours, and minutes.

The process remains running while at least one recurring job is registered. It exits after the initial run when every enabled Renamarr job has `schedule.enabled` set to `false`.

### Logging

Renamarr uses structlog with Python's standard logging. Logs are always written to stdout. `LOG_FORMAT=text` is the default; `LOG_FORMAT=json` produces one JSON object per line on stdout and in instance files.

Both formats include a UTC timestamp, level, logger name, and the available `arr_type`, `instance`, and `item` context. Text output uses colors only when stdout is an interactive terminal; files never contain colors. `LOG_LEVEL=DEBUG` adds source locations. Exception tracebacks do not include local-variable dumps. Third-party libraries log at `WARNING` or above, subject to the configured output level.

`arr_type` identifies the Arr application (`sonarr` or `radarr`), and `instance` is its configured name. The OpenTelemetry resource attribute `service.name` identifies Renamarr itself and defaults to `renamarr`. Resource attributes are attached to OTLP records and are not automatically included in local output.

Messages have separate structured properties, such as a batch `description`, folder `titles`, and affected `item_ids`. For example, text output includes:

```text
2026-09-08T12:00:00.000000Z [info     ] File rename completed successfully [renamarr.renamarr] arr_type=sonarr description=Example instance=shows item_ids=(1,)
```

Each run ends with `Finished Renamarr successfully` at `INFO` or `Finished Renamarr with failures` at `ERROR`, with numeric properties for `items_found`, `failure_count`, and the `success`, `failed`, and `skipped` totals for each of `analysis`, `file_renames`, and `folder_renames`. A JSON summary looks like this:

```json
{"event": "Finished Renamarr successfully", "items_found": 2, "analysis_success": 0, "analysis_failed": 0, "analysis_skipped": 2, "file_renames_success": 1, "file_renames_failed": 0, "file_renames_skipped": 1, "folder_renames_success": 0, "folder_renames_failed": 0, "folder_renames_skipped": 2, "failure_count": 0, "instance": "shows", "arr_type": "sonarr", "level": "info", "logger": "renamarr.renamarr", "timestamp": "2026-09-08T12:00:00.000000Z"}
```

Individual scan failures include `phase` and `item_ids`. At `DEBUG`, an `Items found` event also reports discovery and analysis counts. Consumers of the previous Loguru message layout should use these structured properties when updating their log queries.

### File Logging

Set `sonarr[].renamarr.log_to_file` or `radarr[].renamarr.log_to_file` to `true` to enable per-instance log files. If the target log path is not writable, renamarr logs a warning to stdout and continues running without logging to file.

When enabled, logs for that instance are written under `LOG_DIR` (`/logs` by default) using one of these paths:

- `sonarr/<name>.log`
- `radarr/<name>.log`

_Don't forget to mount /logs outside the container to persist log files_

_To avoid permission issues when creating log files, set the user option in docker-compose to match the desired runtime UID/GID._

#### Logging Configuration and Defaults

| Environment Variable | Description                                                                                                                 | Default  |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------- | -------- |
| `LOG_LEVEL`          | Case-insensitive standard logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. `DEBUG` adds source locations. | `INFO`   |
| `LOG_FORMAT`         | `text` or `json`, applied to stdout and instance files.                                                                     | `text`   |
| `LOG_DIR`            | Directory containing per-instance log files.                                                                                | `/logs`  |
| `LOG_ROTATION`       | Daily rotation time in local time, using `HH:MM` (24-hour clock).                                                           | `00:00`  |
| `LOG_RETENTION`      | Positive whole number of days, such as `1 day` or `7 days`.                                                                 | `7 days` |

Rotation happens on the first log record emitted after the scheduled time. After rollover, archives whose modification time is at least `LOG_RETENTION` days old are removed. Cleanup recognizes both new `<name>.log.YYYY-MM-DD` archives and legacy Loguru `<name>.YYYY-MM-DD_HH-MM-SS_microseconds.log` archives, including numbered collision suffixes. It preserves the active file and other instances' archives. Quiet instances are cleaned up when they next rotate.

Rotation and retention accept only the syntax shown above; other former Loguru options, including size-based rotation, are unsupported. Invalid settings produce a configuration error. File rotation settings are checked when file logging is enabled.

### OpenTelemetry Logs

OTLP export is optional and sends logs alongside the existing stdout output. To send logs to an existing Grafana Alloy OTLP/HTTP receiver reachable as `alloy:4318`, add these variables to the Renamarr service's Compose configuration:

```yaml
environment:
  OTEL_LOGS_EXPORTER: otlp
  OTEL_EXPORTER_OTLP_ENDPOINT: http://alloy:4318
```

The exporter appends `/v1/logs` to the base endpoint. Alloy must have an OTLP receiver listening for HTTP traffic on that address and a logs pipeline connected to your destination. Alternatively, configure `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://alloy:4318/v1/logs`; this complete URL overrides the base endpoint and is used as supplied.

| Environment Variable               | Description                                                                               | Default                        |
| ---------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------ |
| `OTEL_LOGS_EXPORTER`               | `otlp` enables export; `none` disables it.                                                | `none`                         |
| `OTEL_EXPORTER_OTLP_ENDPOINT`      | Base HTTP endpoint; `/v1/logs` is appended.                                               | `http://localhost:4318`        |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | Complete logs URL overriding the base endpoint.                                           | Derived from the base endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL`      | Export protocol; only `http/protobuf` is supported.                                       | `http/protobuf`                |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | Logs-specific protocol overriding the general setting; only `http/protobuf` is supported. | General protocol setting       |
| `OTEL_SERVICE_NAME`                | OpenTelemetry `service.name` resource attribute.                                          | `renamarr`                     |
| `OTEL_SDK_DISABLED`                | `true` disables OTLP export, even when requested.                                         | `false`                        |

The SDK also reads standard environment settings:

- `OTEL_RESOURCE_ATTRIBUTES` for additional resource properties. A `service.name` here overrides the default; `OTEL_SERVICE_NAME` takes precedence over it.
- `OTEL_EXPORTER_OTLP_HEADERS` for authentication headers; `OTEL_EXPORTER_OTLP_CERTIFICATE`, `OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE`, and `OTEL_EXPORTER_OTLP_CLIENT_KEY` for TLS certificate paths.
- `OTEL_EXPORTER_OTLP_TIMEOUT` for the HTTP export timeout in seconds and `OTEL_EXPORTER_OTLP_COMPRESSION` for compression. The corresponding `OTEL_EXPORTER_OTLP_LOGS_*` variables override these general exporter settings, including headers and certificates.
- `OTEL_BLRP_SCHEDULE_DELAY` (milliseconds), `OTEL_BLRP_MAX_QUEUE_SIZE`, and `OTEL_BLRP_MAX_EXPORT_BATCH_SIZE` for batching.

OTLP records carry the event message as their body, structured properties as attributes, and native exception information. If an active OpenTelemetry span exists, its trace and span IDs are included in exported logs and local output. Renamarr does not yet create traces or metrics.

Exporter and HTTP transport diagnostics stay local to prevent export feedback loops. An unreachable collector leaves local logging and jobs operational. Pending logs are drained during normal completion and SIGINT/SIGTERM shutdown; the supplied Compose files allow a 35-second stop grace period.

Choose one ingestion route for Renamarr in Alloy: either receive native OTLP logs or collect its stdout. Collecting both into the same backend duplicates application logs. `LOG_FORMAT` controls local rendering independently of OTLP.

### Configuration

| Name                                                       | Type    | Required | Default Value | Description                                                                                                                                      |
| ---------------------------------------------------------- | ------- | -------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sonarr`                                                   | Array   | No       | []            | Sonarr instances; when present, must contain at least one instance                                                                               |
| `sonarr[].name`                                            | string  | Yes      | N/A           | user friendly instance name, used in log messages                                                                                                |
| `sonarr[].url`                                             | string  | Yes      | N/A           | url for sonarr instance                                                                                                                          |
| `sonarr[].api_key`                                         | string  | Yes      | N/A           | api_key for sonarr instance                                                                                                                      |
| `sonarr[].renamarr.enabled`                                | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `sonarr[].renamarr.hourly_job`                             | boolean | No       | N/A           | **Deprecated:** compatibility alias for `schedule.enabled`; an explicit `schedule.enabled` takes precedence                                      |
| `sonarr[].renamarr.schedule.enabled`                       | boolean | No       | True          | enables recurring Renamarr jobs; when false, Renamarr runs once at startup                                                                       |
| `sonarr[].renamarr.schedule.interval.days`                 | integer | No       | 0             | days between Renamarr jobs                                                                                                                       |
| `sonarr[].renamarr.schedule.interval.hours`                | integer | No       | 0             | hours between Renamarr jobs                                                                                                                      |
| `sonarr[].renamarr.schedule.interval.minutes`              | integer | No       | 0             | minutes between Renamarr jobs                                                                                                                    |
| `sonarr[].renamarr.analyze_files`                          | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio/video codecs have changed. |
| `sonarr[].renamarr.rename_folders`                         | boolean | No       | False         | This will rename series folders when the current series folder no longer matches your MediaFormat                                                |
| `sonarr[].renamarr.log_to_file`                            | boolean | No       | False         | writes logs for this Sonarr instance to `LOG_DIR/sonarr/<name>.log` with daily rotation                                                          |
| `sonarr[].renamarr.command_polling.timeout_seconds`        | integer | No       | 120           | maximum time to wait for each analysis, rename, or rescan command                                                                                |
| `sonarr[].renamarr.command_polling.check_interval_seconds` | integer | No       | 3             | seconds between command-status checks after the immediate first check                                                                            |
| `radarr`                                                   | Array   | No       | []            | Radarr instances; when present, must contain at least one instance                                                                               |
| `radarr[].name`                                            | string  | Yes      | N/A           | user friendly instance name, used in log messages                                                                                                |
| `radarr[].url`                                             | string  | Yes      | N/A           | url for radarr instance                                                                                                                          |
| `radarr[].api_key`                                         | string  | Yes      | N/A           | api_key for radarr instance                                                                                                                      |
| `radarr[].renamarr.enabled`                                | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `radarr[].renamarr.hourly_job`                             | boolean | No       | N/A           | **Deprecated:** compatibility alias for `schedule.enabled`; an explicit `schedule.enabled` takes precedence                                      |
| `radarr[].renamarr.schedule.enabled`                       | boolean | No       | True          | enables recurring Renamarr jobs; when false, Renamarr runs once at startup                                                                       |
| `radarr[].renamarr.schedule.interval.days`                 | integer | No       | 0             | days between Renamarr jobs                                                                                                                       |
| `radarr[].renamarr.schedule.interval.hours`                | integer | No       | 0             | hours between Renamarr jobs                                                                                                                      |
| `radarr[].renamarr.schedule.interval.minutes`              | integer | No       | 0             | minutes between Renamarr jobs                                                                                                                    |
| `radarr[].renamarr.analyze_files`                          | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio/video codecs have changed. |
| `radarr[].renamarr.rename_folders`                         | boolean | No       | False         | This will rename movie folders when the current movie folder no longer matches your MediaFormat                                                  |
| `radarr[].renamarr.log_to_file`                            | boolean | No       | False         | writes logs for this Radarr instance to `LOG_DIR/radarr/<name>.log` with daily rotation                                                          |
| `radarr[].renamarr.command_polling.timeout_seconds`        | integer | No       | 120           | maximum time to wait for each analysis, rename, or rescan command                                                                                |
| `radarr[].renamarr.command_polling.check_interval_seconds` | integer | No       | 3             | seconds between command-status checks after the immediate first check                                                                            |

Schedule interval values must be non-negative integers, and the combined interval cannot exceed 30 days. When scheduling is enabled, the combined interval must be greater than zero. A zero interval is valid only when `schedule.enabled` is `false`.

When `schedule.interval` is omitted or empty, Renamarr uses the default interval of one hour.

Command-polling values must be positive integers. `check_interval_seconds` cannot exceed `timeout_seconds`. The section is optional; omitting `command_polling`, or the entire `renamarr` section, uses a two-minute timeout and a three-second check interval.

### Docker Heartbeat

The container publishes application health through Docker's native health status. Renamarr refreshes an internal heartbeat while the scheduler is idle and from a background thread while a job is running. The health check is observational: Docker Compose's `restart` policy does not restart a running container solely because it becomes unhealthy. A logically stuck job can remain healthy while its heartbeat thread continues running.

The heartbeat is stored under `/tmp`. Containers invoked by an external scheduler may finish before Docker runs a health check. For these runs, use the container’s completion status and Renamarr logs rather than Docker health status.

#### Read-only Root Filesystem

The included Compose configurations run Renamarr with a read-only root filesystem. The heartbeat is written to `/tmp`, so that path is mounted as a writable `tmpfs`.

When file logging is enabled, `/logs` must also be mounted as a writable volume; otherwise, Renamarr warns and continues with stdout logging.

### Local Development

See [Local Development](docs/local-development.md) for local development requirements, environment details, and startup commands.

The mise configuration installs the development toolchain and provides tasks for the common workflows:

```shell
mise install
mise run sync
mise run check
mise run audit
mise run docker-build
```
