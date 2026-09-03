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
   - _Set `lidarr[].renamarr.schedule.enabled` to `false` for every enabled Renamarr instance._
3. Invoke the app from your scheduler using the provided [docker-compose.yml](example/external-scheduler/docker-compose.yml)

#### Troubleshooting

Image tags ending in `-dev` can be used for troubleshooting purposes, but are not intended for normal usage. Pre-release images are tagged with their specific release version and do not change or overwrite the `latest` or `latest-dev` tags.

## How it works

### Renamarr

This job uses the [Sonarr API](https://sonarr.tv/docs/api/), [Radarr API](https://radarr.video/docs/api/), and [Lidarr API](https://github.com/devopsarr/lidarr-py#documentation-for-api-endpoints) to do the following

Sonarr API access uses [devopsarr/sonarr-py](https://github.com/devopsarr/sonarr-py), Radarr API access uses [devopsarr/radarr-py](https://github.com/devopsarr/radarr-py), and Lidarr API access uses [devopsarr/lidarr-py](https://github.com/devopsarr/lidarr-py). Existing Arr configuration remains unchanged.

- Iterate over all items (Movies, Series, or Artists)
  - Checks if any items need to be renamed
    - Radarr [get_api_v3_rename](https://radarr.video/docs/api/#/RenameMovie/get_api_v3_rename)
    - Sonarr [get_api_v3_rename](https://sonarr.tv/docs/api/#/RenameEpisode/get_api_v3_rename)
    - Lidarr [list_rename](https://github.com/devopsarr/lidarr-py/blob/v1.2.1/docs/RenameTrackApi.md)
  - Triggers a rename on any item that need be renamed
    - Series renames are batched up, for one rename call per series
    - Movie renames are discovered per movie, then initiated in one batch command with all movie IDs that need a rename
    - Track renames are batched up, for one rename call per artist

#### Analyze Files

This config option is useful if you have audio/video codec information as part of your mediaformat, and you are transcoding files after import. This will initiate a rescan of the files in your library, so that the mediainfo will be updated. Then renamarr will come through and detect changes, and rename the files. Lidarr uses a direct `RescanFolders` command with discovery of new artists disabled.

#### Rename Folders

This config option will rename series, movie, or artist folders when they no longer match your configured MediaFormat.

- uses [/api/v3/series/{id}/folder](https://sonarr.tv/docs/api/#/SeriesFolder/get_api_v3_series__id__folder) endpoint to determine if the series folder requires an update
- uses [/api/v3/series/editor](https://sonarr.tv/docs/api/#v3/tag/serieseditor/PUT/api/v3/series/editor) endpoint to update series rootFolderPath to it's current value
  - moving the folder in place
- uses [/api/v3/movie/{id}/folder](https://radarr.video/docs/api/#/MovieFolder/get_api_v3_movie__id__folder) endpoint to determine if the movie folder requires an update
- uses [/api/v3/movie/editor](https://radarr.video/docs/api/#/MovieEditor/put_api_v3_movie_editor) endpoint to update movie rootFolderPath to it's current value
  - moving the folder in place
- uses Lidarr's [`/api/v1/artist/lookup`](https://github.com/devopsarr/lidarr-py/blob/v1.2.1/docs/ArtistLookupApi.md) endpoint to determine the expected artist folder
- uses Lidarr's [`/api/v1/artist/editor`](https://github.com/devopsarr/lidarr-py/blob/v1.2.1/docs/ArtistEditorApi.md) endpoint to update artist rootFolderPath to its current value
  - moving the artist folder in place; album-directory changes remain part of the track rename workflow
- sends a Sonarr `RescanSeries` command to rescan series after successful folder moves
- sends a Radarr `RefreshMovie` command to rescan movies after successful folder moves
- sends a Lidarr `RescanFolders` command to rescan artists after successful folder moves
- Series, movies, and artists are processed in bulk at the end of the run, **per root folder**

#### Command Polling and Partial Results

Analysis, file rename, and post-move rescan commands use the same polling settings. Renamarr checks each command immediately, then checks every `command_polling.check_interval_seconds` until it succeeds, reports a completed failure, encounters a status-check error, or reaches `command_polling.timeout_seconds`. The timeout applies separately to each asynchronous command; it is not an HTTP request or whole-scan timeout.

### Usage

The application runs enabled jobs immediately on startup. Renamarr jobs repeat every hour by default. Set `renamarr.schedule.enabled` to `false` to run once, or configure the interval in days, hours, and minutes.

The process remains running while at least one recurring job is registered. It exits after the initial run when every enabled Renamarr job has `schedule.enabled` set to `false`.

Logs are always written to stdout.

Each successful run ends with file and folder rename totals in the following format:

```text
Finished Renamarr successfully | file renames: [ success=0, failed=0, skipped=373 ] | folder renames: [ success=0, failed=0, skipped=373 ]
```

Failed runs report the same totals at `ERROR` level after their individual errors. At `DEBUG` level, each run also reports its item count and analysis outcomes.

### File Logging

Set `sonarr[].renamarr.log_to_file`, `radarr[].renamarr.log_to_file`, or `lidarr[].renamarr.log_to_file` to `true` to enable per-instance log files. If the target log path is not writable, renamarr logs a warning to stdout and continues running without logging to file.

When enabled, logs for that instance are written under `LOG_DIR` (`/logs` by default) using one of these paths:

- `sonarr/<name>.log`
- `radarr/<name>.log`
- `lidarr/<name>.log`

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
| `lidarr`                                                   | Array   | No       | []            | Lidarr instances; when present, must contain at least one instance                                                                               |
| `lidarr[].name`                                            | string  | Yes      | N/A           | user friendly instance name, used in log messages                                                                                                |
| `lidarr[].url`                                             | string  | Yes      | N/A           | url for lidarr instance                                                                                                                          |
| `lidarr[].api_key`                                         | string  | Yes      | N/A           | api_key for lidarr instance                                                                                                                      |
| `lidarr[].renamarr.enabled`                                | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `lidarr[].renamarr.hourly_job`                             | boolean | No       | N/A           | **Deprecated:** compatibility alias for `schedule.enabled`; an explicit `schedule.enabled` takes precedence                                      |
| `lidarr[].renamarr.schedule.enabled`                       | boolean | No       | True          | enables recurring Renamarr jobs; when false, Renamarr runs once at startup                                                                       |
| `lidarr[].renamarr.schedule.interval.days`                 | integer | No       | 0             | days between Renamarr jobs                                                                                                                       |
| `lidarr[].renamarr.schedule.interval.hours`                | integer | No       | 0             | hours between Renamarr jobs                                                                                                                      |
| `lidarr[].renamarr.schedule.interval.minutes`              | integer | No       | 0             | minutes between Renamarr jobs                                                                                                                    |
| `lidarr[].renamarr.analyze_files`                          | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio codecs have changed.       |
| `lidarr[].renamarr.rename_folders`                         | boolean | No       | False         | This will rename artist folders when the current artist folder no longer matches your MediaFormat                                                |
| `lidarr[].renamarr.log_to_file`                            | boolean | No       | False         | writes logs for this Lidarr instance to `LOG_DIR/lidarr/<name>.log` with daily rotation                                                          |
| `lidarr[].renamarr.command_polling.timeout_seconds`        | integer | No       | 120           | maximum time to wait for each analysis, rename, or rescan command                                                                                |
| `lidarr[].renamarr.command_polling.check_interval_seconds` | integer | No       | 3             | seconds between command-status checks after the immediate first check                                                                            |

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
