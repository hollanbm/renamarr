# Renamarr

[![codecov](https://codecov.io/gh/hollanbm/renamarr/graph/badge.svg?token=8MJ61PXR4V)](https://codecov.io/gh/hollanbm/renamarr)

## Quick Start

### docker

1. Copy/Rename [config.yml.example](example/config.yml.example) to `config.yml`
2. Update `config.yml` as needed.
   - See [Configuration](#configuration) for further explanation
3. Bring up app using provided [docker-compose.yml](example/docker-compose.yml)

#### Troubleshooting

Image tags ending in `-dev` can be used for troubleshooting purposes, but are not intended for normal usage. Pre-release images are tagged with their specific release version and do not change or overwrite the `latest` or `latest-dev` tags.

## How it works

### Renamarr

This job uses the [Sonarr API](https://sonarr.tv/docs/api/)/[Radarr API](https://radarr.video/docs/api/) to do the following

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
- sends a Radarr `RefreshMovie` command to rescan movies after successful folder moves
- Series and movies are processed in bulk at the end of the run, **per root folder**

### Series Scanner (Sonarr Only)

> [!IMPORTANT]
> This feature is in maintenance mode and will not receive further development or enhancements. Its usage will be evaluated in the future to determine whether it should be removed completely.

This job uses the [Sonarr API](https://sonarr.tv/docs/api/) to do the following

- Iterate over continuing [series](https://sonarr.tv/docs/api/#/Series/get_api_v3_series)
  - If a series has an episode airing within `config.sonarr[].series_scanner.hours_before_air`
    - default value of 4, max value of 12
  - OR
  - An episode that has aired previously
  - With a title of TBA (excluding specials)
    - will trigger a series refresh, to hopefully pull new info from The TVDB

This should prevent too many API calls to the TVDB. When recurring scans are enabled, individual series are checked every 55–65 minutes.

### Usage

The application runs enabled jobs immediately on startup. Renamarr jobs repeat every hour by default. Set `renamarr.schedule.enabled` to `false` to run once, or configure the interval in days, hours, and minutes.

Logs are always written to stdout.

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

### Configuration

| Name                                          | Type    | Required | Default Value | Description                                                                                                                                      |
| --------------------------------------------- | ------- | -------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sonarr`                                      | Array   | No       | []            | Sonarr instances; when present, must contain at least one instance                                                                               |
| `sonarr[].name`                               | string  | Yes      | N/A           | user friendly instance name, used in log messages                                                                                                |
| `sonarr[].url`                                | string  | Yes      | N/A           | url for sonarr instance                                                                                                                          |
| `sonarr[].api_key`                            | string  | Yes      | N/A           | api_key for sonarr instance                                                                                                                      |
| `sonarr[].series_scanner.enabled`             | boolean | No       | False         | enables/disables series_scanner functionality                                                                                                    |
| `sonarr[].series_scanner.hourly_job`          | boolean | No       | False         | enables recurring scans every 55–65 minutes; when false, the scanner runs once at startup                                                        |
| `sonarr[].series_scanner.hours_before_air`    | integer | No       | 4             | The number of hours before an episode has aired, to trigger a rescan when title is TBA                                                           |
| `sonarr[].renamarr.enabled`                   | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `sonarr[].renamarr.hourly_job`                | boolean | No       | N/A           | **Deprecated:** compatibility alias for `schedule.enabled`; an explicit `schedule.enabled` takes precedence                                      |
| `sonarr[].renamarr.schedule.enabled`          | boolean | No       | True          | enables recurring Renamarr jobs; when false, Renamarr runs once at startup                                                                       |
| `sonarr[].renamarr.schedule.interval.days`    | integer | No       | 0             | days between Renamarr jobs                                                                                                                       |
| `sonarr[].renamarr.schedule.interval.hours`   | integer | No       | 0             | hours between Renamarr jobs                                                                                                                      |
| `sonarr[].renamarr.schedule.interval.minutes` | integer | No       | 0             | minutes between Renamarr jobs                                                                                                                    |
| `sonarr[].renamarr.analyze_files`             | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio/video codecs have changed. |
| `sonarr[].renamarr.rename_folders`            | boolean | No       | False         | This will rename series folders when the current series folder no longer matches your MediaFormat                                                |
| `sonarr[].renamarr.log_to_file`               | boolean | No       | False         | writes logs for this Sonarr instance to `LOG_DIR/sonarr/<name>.log` with daily rotation                                                          |
| `radarr`                                      | Array   | No       | []            | Radarr instances; when present, must contain at least one instance                                                                               |
| `radarr[].name`                               | string  | Yes      | N/A           | user friendly instance name, used in log messages                                                                                                |
| `radarr[].url`                                | string  | Yes      | N/A           | url for radarr instance                                                                                                                          |
| `radarr[].api_key`                            | string  | Yes      | N/A           | api_key for radarr instance                                                                                                                      |
| `radarr[].renamarr.enabled`                   | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `radarr[].renamarr.hourly_job`                | boolean | No       | N/A           | **Deprecated:** compatibility alias for `schedule.enabled`; an explicit `schedule.enabled` takes precedence                                      |
| `radarr[].renamarr.schedule.enabled`          | boolean | No       | True          | enables recurring Renamarr jobs; when false, Renamarr runs once at startup                                                                       |
| `radarr[].renamarr.schedule.interval.days`    | integer | No       | 0             | days between Renamarr jobs                                                                                                                       |
| `radarr[].renamarr.schedule.interval.hours`   | integer | No       | 0             | hours between Renamarr jobs                                                                                                                      |
| `radarr[].renamarr.schedule.interval.minutes` | integer | No       | 0             | minutes between Renamarr jobs                                                                                                                    |
| `radarr[].renamarr.analyze_files`             | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio/video codecs have changed. |
| `radarr[].renamarr.rename_folders`            | boolean | No       | False         | This will rename movie folders when the current movie folder no longer matches your MediaFormat                                                  |
| `radarr[].renamarr.log_to_file`               | boolean | No       | False         | writes logs for this Radarr instance to `LOG_DIR/radarr/<name>.log` with daily rotation                                                          |

Schedule interval values must be non-negative integers. When scheduling is enabled, the combined interval must be greater than zero. A zero interval is valid only when `schedule.enabled` is `false`.

When `schedule.interval` is omitted or empty, Renamarr uses the default interval of one hour.

### Local Development

See [Local Development](docs/local-development.md) for local development requirements, environment details, and startup commands.

Dependency audits are run with `uv audit --frozen --preview-features audit`.
