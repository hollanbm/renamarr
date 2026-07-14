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

This job uses the [Sonarr API](https://sonarr.tv/docs/api/) to do the following

- Iterate over continuing [series](https://sonarr.tv/docs/api/#/Series/get_api_v3_series)
  - If a series has an episode airing within `config.sonarr[].series_scanner.hours_before_air`
    - default value of 4, max value of 12
  - OR
  - An episode that has aired previously
  - With a title of TBA (excluding specials)
    - will trigger a series refresh, to hopefully pull new info from The TVDB

This should prevent too many API calls to the TVDB, refreshing individual series, hourly

### Usage

The application runs immediately on startup, and then continue to schedule jobs every hour (+- 5 minutes) after the first execution.

Logs are always written to stdout.

### File Logging

Set `sonarr[].renamarr.log_to_file` or `radarr[].renamarr.log_to_file` to `true` to enable per-instance log files. If the target log path is not writable, renamarr logs a warning to stdout and continues running without logging to file.

When enabled, logs for that instance are written under `/logs` using one of these paths:

- `sonarr/<name>.log`
- `radarr/<name>.log`

_Don't forget to mount /logs outside the container to persist log files_

_To avoid permission issues when creating log files, set the user option in docker-compose to match the desired runtime UID/GID._

#### Logging Configuration and Defaults

| Environment Variable | Description                                                                                           | Default  |
| -------------------- | ----------------------------------------------------------------------------------------------------- | -------- |
| `LOG_LEVEL`          | Log level passed to Loguru for stdout and file sinks. `DEBUG` also adds source location to log lines. | `INFO`   |
| `LOG_FORMAT`         | Log format for stdout and file sinks. Set to `json` for Loguru structured JSON logs.                  | `text`   |
| `LOG_ROTATION`       | Rotation schedule passed to Loguru for file log rotation.                                             | `00:00`  |
| `LOG_RETENTION`      | Retention period passed to Loguru for rotated log files.                                              | `7 days` |

_For more details on `LOG_RETENTION` or `LOG_ROTATION` values, see the [official documentation](https://loguru.readthedocs.io/en/stable/overview.html#easier-file-logging-with-rotation-retention-compression)_

### Observability

Renamarr can push OpenTelemetry metrics and traces to an OTLP Collector or Grafana Alloy. This is designed for the hourly/one-shot execution model: Renamarr does not expose a `/metrics` endpoint and does not run or require a web framework.

Set `RENAMARR_OTEL_ENABLED=true` and configure the standard OpenTelemetry exporter environment variables for your collector:

```yaml
environment:
  RENAMARR_OTEL_ENABLED: "true"
  OTEL_SERVICE_NAME: renamarr
  OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318
```

Renamarr sends OTLP over HTTP/protobuf. The collector should receive OTLP/HTTP from Renamarr, export the metrics pipeline to a Prometheus-compatible backend with `prometheusremotewrite`, and export the traces pipeline to Tempo with OTLP. A minimal collector/Alloy topology looks like this:

```yaml
receivers:
  otlp:
    protocols:
      http:

exporters:
  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheusremotewrite]
    traces:
      receivers: [otlp]
      exporters: [otlp/tempo]
```

Renamarr emits job, operation, and Sonarr/Radarr command metrics. The OpenTelemetry instrument names use dots; Prometheus-compatible backends commonly expose them with underscores and `_total`/`_seconds` suffixes:

- `renamarr_job_runs_total`
- `renamarr_job_duration_seconds`
- `renamarr_job_last_started_seconds`
- `renamarr_job_last_completed_seconds`
- `renamarr_job_last_success_seconds`
- `renamarr_operation_runs_total`
- `renamarr_operation_items_total`
- `renamarr_operation_candidate_items_total`
- `renamarr_arr_command_runs_total`
- `renamarr_arr_command_duration_seconds`

Job metrics include `service`, `name`, and `job` labels, with `result` on run and duration metrics. Operation metrics include `service`, `name`, `operation`, and `result` where applicable. Command metrics include `service`, `name`, `command`, and `result`.

Arr command duration histograms use explicit buckets up to 300 seconds to match the five-minute command timeout.

The old per-service operation metrics (`renamarr_sonarr_rename_items_total`, `renamarr_sonarr_folder_rename_items_total`, `renamarr_radarr_rename_items_total`, and `renamarr_radarr_folder_rename_items_total`) were replaced by the generic `renamarr_operation_*` metrics.

An example Grafana dashboard using the dashboard v2 JSON model is available at [example/grafana/renamarr-dashboard.v2.json](example/grafana/renamarr-dashboard.v2.json). It can be pasted directly into Grafana's dashboard JSON Model editor. It uses Prometheus-compatible metric queries, Tempo TraceQL queries, and optional Loki log queries. Prometheus panels can be narrowed with the `instance_name` dropdown variable, which defaults to All configured instances. Tempo TraceQL metric panels omit an explicit step so Grafana and Tempo can choose a valid duration, and those panels override their time range to 24 hours to match Tempo's default `query_frontend.metrics.max_duration` limit. The dashboard is portable by datasource type; if your Grafana instance has multiple Prometheus, Tempo, or Loki datasources, pin the desired datasource name in each dashboard `DataQuery`. If you set `OTEL_SERVICE_NAME` to something other than `renamarr`, update the dashboard's `otel_service_name` variable.

Example Prometheus-style alert rules are available at [example/grafana/renamarr-alerts.yaml](example/grafana/renamarr-alerts.yaml). They cover stale successful jobs, failed jobs, failed or timed-out Arr commands, failed operations, and high job duration.

### Configuration

| Name                                       | Type    | Required | Default Value | Description                                                                                                                                      |
| ------------------------------------------ | ------- | -------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sonarr`                                   | Array   | Yes      | []            | One or more sonarr instances                                                                                                                     |
| `sonarr[].name`                            | string  | Yes      | N/A           | user friendly instance name, used in log messages                                                                                                |
| `sonarr[].url`                             | string  | Yes      | N/A           | url for sonarr instance                                                                                                                          |
| `sonarr[].api_key`                         | string  | Yes      | N/A           | api_key for sonarr instance                                                                                                                      |
| `sonarr[].series_scanner.enabled`          | boolean | No       | False         | enables/disables series_scanner functionality                                                                                                    |
| `sonarr[].series_scanner.hourly_job`       | boolean | No       | False         | disables hourly job. App will exit after first execution                                                                                         |
| `sonarr[].series_scanner.hours_before_air` | integer | No       | 4             | The number of hours before an episode has aired, to trigger a rescan when title is TBA                                                           |
| `sonarr[].renamarr.enabled`                | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `sonarr[].renamarr.hourly_job`             | boolean | No       | False         | disables hourly job. App will exit after first execution                                                                                         |
| `sonarr[].renamarr.analyze_files`          | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio/video codecs have changed. |
| `sonarr[].renamarr.rename_folders`         | boolean | No       | False         | This will rename series folders when the current series folder no longer matches your MediaFormat                                                |
| `sonarr[].renamarr.log_to_file`            | boolean | No       | False         | writes logs for this Sonarr instance to `/logs/sonarr/<name>.log` with daily rotation                                                            |
| `radarr[].renamarr.enabled`                | boolean | No       | False         | enables/disables renamarr functionality                                                                                                          |
| `radarr[].renamarr.hourly_job`             | boolean | No       | False         | disables hourly job. App will exit after first execution                                                                                         |
| `radarr[].renamarr.analyze_files`          | boolean | No       | False         | This will initiate a rescan of the files in your library. This is helpful if you are transcoding files, and the audio/video codecs have changed. |
| `radarr[].renamarr.rename_folders`         | boolean | No       | False         | This will rename movie folders when the current movie folder no longer matches your MediaFormat                                                  |
| `radarr[].renamarr.log_to_file`            | boolean | No       | False         | writes logs for this Radarr instance to `/logs/radarr/<name>.log` with daily rotation                                                            |

### Local Development

See [Local Development](docs/local-development.md) for local development requirements, environment details, and startup commands.

Dependency audits are run with `uv audit --frozen --preview-features audit`.
