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
    - Movie renames are discovered per movie, then initiated in one batch command with all movie IDs that need a rename. Radarr processes all files associated with each movie.
    - After a file rename command completes, Renamarr checks each item's rename preview again. An item counts as successful only when no files still need renaming; remaining renames and verification errors count as failures without affecting successfully renamed items in the same batch.

If a movie repeatedly needs renaming, check Radarr's logs for filename collisions or file access errors. Radarr can complete a command successfully even when individual files cannot be renamed. Multiple files for the same movie must have distinct target filenames; if a target already exists, resolve the duplicate or adjust Radarr's naming configuration. Renamarr leaves those files intact and retries pending renames on subsequent runs.

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
- waits for each folder move command to complete successfully before submitting its rescan, using the default rescan priority
- Series and movies are processed in bulk at the end of the run, **per root folder**

#### Command Polling and Partial Results

Any file-rename failure skips the entire folder phase and counts its items as skipped. Folder move submission, command identification, polling, or completion failures mark that root-folder batch as failed and prevent its rescan; other root-folder batches can continue. Renamarr identifies moves by comparing command lists before and after the editor request, matching the destination root, item IDs, and source paths. A missing or ambiguous match fails the batch. An exact queued or running command can be reused when the service deduplicates the request.

Analysis, file rename, folder move, and post-move rescan commands use the same polling settings. Renamarr checks each command immediately, then checks every `command_polling.check_interval_seconds` until it succeeds, reports a completed failure, encounters a status-check error, or reaches `command_polling.timeout_seconds`. Failed, aborted, cancelled, and orphaned commands stop polling as unsuccessful. The timeout applies separately to each asynchronous command; it is not an HTTP request or whole-scan timeout.

### Usage

The application runs enabled jobs immediately on startup. Renamarr jobs repeat every hour by default. Set `renamarr.schedule.enabled` to `false` to run once, or configure the interval in days, hours, and minutes.

The process remains running while at least one recurring job is registered. It exits after the initial run when every enabled Renamarr job has `schedule.enabled` set to `false`.

Logs are always written to stdout.

Each successful run ends with file and folder rename totals in the following format:

```text
Finished Renamarr successfully | file renames: [ success=0, failed=0, skipped=373 ] | folder renames: [ success=0, failed=0, skipped=373 ]
```

Failed runs report the same totals at `ERROR` level after their individual errors. At `DEBUG` level, each run also reports its item count and analysis outcomes.

Incomplete file rename errors identify the pending Radarr movie file IDs or Sonarr episode file IDs in square brackets, such as `file ID [10200] still needs renaming` or `file IDs [10200, 10201] still need renaming`, without a trailing comma.

### File Logging

Set `sonarr[].renamarr.log_to_file` or `radarr[].renamarr.log_to_file` to `true` to enable per-instance log files. If the target log path is not writable, renamarr logs a warning to stdout and continues running without logging to file.

When enabled, logs for that instance are written under `LOG_DIR` (`/logs` by default) using one of these paths:

- `sonarr/<name>.log`
- `radarr/<name>.log`

_Don't forget to mount /logs outside the container to persist log files_

_To avoid permission issues when creating log files, set the user option in docker-compose to match the desired runtime UID/GID._

#### Logging Configuration and Defaults

| Environment Variable | Description                                                                                           | Default  |
| -------------------- | ----------------------------------------------------------------------------------------------------- | -------- |
| `LOG_LEVEL`          | Log level passed to Loguru for stdout and file sinks. `DEBUG` also adds source location to log lines. | `INFO`   |
| `LOG_DIR`            | Directory containing per-instance log files.                                                          | `/logs`  |
| `LOG_ROTATION`       | Rotation schedule passed to Loguru for file log rotation.                                             | `00:00`  |
| `LOG_RETENTION`      | Retention period passed to Loguru for rotated log files.                                              | `7 days` |

_For more details on `LOG_RETENTION` or `LOG_ROTATION` values, see the [official documentation](https://loguru.readthedocs.io/en/stable/overview.html#easier-file-logging-with-rotation-retention-compression)_

### OpenTelemetry

Renamarr optionally exports metrics and traces using OTLP HTTP/protobuf. Set a shared endpoint to enable both signals:

```yaml
environment:
  OTEL_EXPORTER_OTLP_ENDPOINT: http://alloy:4318
  OTEL_RESOURCE_ATTRIBUTES: deployment.environment.name=home
```

No telemetry is exported without an endpoint. A shared endpoint receives metrics at `/v1/metrics` and traces at `/v1/traces`. Signal-specific endpoint values are complete URLs and override the shared endpoint for that signal.

Common settings and Renamarr's defaults:

| Variable                                        | Purpose                                                                                                |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `OTEL_EXPORTER_OTLP_ENDPOINT`                   | Collector base URL; enables metrics and traces. Telemetry is disabled until an endpoint is configured. |
| `OTEL_SERVICE_NAME`                             | Service name; Renamarr defaults to `renamarr`.                                                         |
| `OTEL_RESOURCE_ATTRIBUTES`                      | Add resource attributes such as `deployment.environment.name=home`.                                    |
| `OTEL_EXPORTER_OTLP_HEADERS`                    | Authentication headers for collectors that require them.                                               |
| `OTEL_EXPORTER_OTLP_CERTIFICATE`                | PEM CA certificate file for a collector using a private CA. TLS verification remains enabled.          |
| `OTEL_METRICS_EXPORTER`, `OTEL_TRACES_EXPORTER` | Set either to `none` to disable that signal. Enabled signals use HTTP/protobuf.                        |

For other options, including signal-specific endpoints, timeouts, and sampling, see the official [OTLP exporter configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/) and [general SDK configuration](https://opentelemetry.io/docs/languages/sdk-configuration/general/) documentation. Renamarr otherwise uses the Python SDK's defaults.

Telemetry initializes once before jobs start and flushes on one-shot completion, startup failure, SIGTERM, and interruption. Export errors do not change rename results or stop scheduling. Shutdown flush attempts have a five-second budget per provider; exporter shutdown may also perform its final collection using configured exporter timeouts.

#### Application metrics

Application metrics carry `arr.service` (`sonarr` or `radarr`) and configured `arr.instance`, plus bounded `kind`, `phase`, and `outcome` attributes where applicable. IDs, titles, paths, bodies, and error messages are excluded from metric labels.

| Metric                                 | Type                | Meaning                                                                       |
| -------------------------------------- | ------------------- | ----------------------------------------------------------------------------- |
| `renamarr.scan.count`                  | Counter             | Completed instance runs by outcome, including unexpected failures.            |
| `renamarr.scan.duration`               | Histogram, seconds  | Instance run duration, including adapter setup and cleanup.                   |
| `renamarr.scan.last_success_timestamp` | Gauge, Unix seconds | Last successful scan; zero until the first success.                           |
| `renamarr.scan.items`                  | Histogram, items    | Library size observed per completed scan.                                     |
| `renamarr.work.items`                  | Counter             | Existing media-item summaries, grouped by phase and succeeded/failed/skipped. |
| `renamarr.rename.candidates`           | Counter             | Unique candidate files per media item, or candidate folders.                  |
| `renamarr.rename.requested`            | Counter             | File/folder units in successfully submitted rename operations.                |
| `renamarr.rename.confirmed`            | Counter             | File/folder units confirmed successful.                                       |
| `renamarr.operation.count`             | Counter             | File/folder batches by outcome.                                               |
| `renamarr.operation.duration`          | Histogram, seconds  | Batch duration, including waiting and file verification or folder rescan.     |
| `renamarr.command.count`               | Counter             | Commands by kind and succeeded/failed/timed_out/status_check_error outcome.   |
| `renamarr.command.duration`            | Histogram, seconds  | Time waiting for each asynchronous command.                                   |
| `renamarr.command.polls`               | Counter             | Status-check attempts, including failed checks.                               |
| `renamarr.job.active`                  | Gauge               | One during an active phase, zero when that phase exits.                       |

The existing rename summaries count media items (series/movies). Physical-file metrics count unique candidate file IDs separately. Files are confirmed only when the item's existing post-command verification succeeds. A failed operation can have partially renamed files, so the unconfirmed difference is **not** a physical-file failure count. Folder confirmation means the existing move/rescan workflow completed; it does not add filesystem verification. Individual physical-file durations are unavailable from the Arr APIs; durations represent batches and commands.

Official urllib3 instrumentation supplies HTTP client latency, size, and error information using its HTTP semantic conventions. HTTP metrics and spans carry the Arr service and instance alongside standard network attributes. Official threading instrumentation propagates trace context. The system-metrics instrumentor reports process CPU time/utilization, current RSS/virtual memory, threads, file descriptors, context switches, and I/O. It does not enable host-wide monitoring.

Suggested alerts include no successful scan within the configured interval plus a grace period, repeated failed runs or command timeouts, increasing run/command latency, and sustained process memory growth. Counters and freshness reset on restart; also alert on absent telemetry. One-shot runs export final values before exiting, so monitor their expected execution schedule externally.

#### Trace contents and runtime compatibility

Each instance run has a root span with child spans for phases, previews, batches, command waits, verification, and HTTP requests. Structured JSON request bodies, media titles, filesystem paths, and identifying IDs may appear in traces. Streams and non-JSON bodies are not captured. API keys and authentication credentials are redacted before trace export, including automatic exception details and credential-bearing URLs. HTTP headers are not captured. Existing stdout/file logging is unchanged; logs are not exported through OTLP.

The runtime remains `dhi.io/debian-base:trixie`, without additional system packages, executables, compilers, or shared libraries. New native dependencies (`psutil`, `wrapt`, `protobuf`, and `charset-normalizer`) require prebuilt wheels. CI validates the actual final image on Linux AMD64 and ARM64 as its nonroot user with a read-only filesystem, dropped capabilities, HTTPS export, and process metric collection. No collector, dashboard, or listening metrics port is added to the application.

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
| `sonarr[].renamarr.command_polling.timeout_seconds`        | integer | No       | 120           | maximum time to wait for each analysis, rename, move, or rescan command                                                                          |
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
| `radarr[].renamarr.command_polling.timeout_seconds`        | integer | No       | 120           | maximum time to wait for each analysis, rename, move, or rescan command                                                                          |
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
