# sonarr-series-scanner

## Quick Start

### docker

1) Copy/Rename [config.yml.example](docker/config.yml.example) to `config.yml`
2) Update `config.yml` as needed.
    * See [Configuration](#configuration) for further explanation
3) Bring up app using provided [docker-compose.yml](docker/docker-compose.yml)

### helm

coming soon

## Requirements

* [Python 3.12](https://www.python.org/downloads/release/python-3123/)
* [pipx](https://pipx.pypa.io/stable/installation/)
* [poetry](https://python-poetry.org/docs/#installation)
* [Sonarr](https://sonarr.tv/)
* This script is intended to be used alongside the `Episode Title Required` setting
  * Settings -> Media Management -> Episode Title Required -> `Always`

### The problem

It is relatively common for the TVDB to be updated the day of, or even after airing. Sonarr refreshes its TVDB cache every 12 hours.

Unfortunately, this can prevent import for up to 12 hours in extreme circumstances.

To solve this, I created this app

## How it works

### Series Scanner
This app uses the [Sonarr API](https://sonarr.tv/docs/api/) to do the following

* Iterate over continuing [series](https://sonarr.tv/docs/api/#/Series/get_api_v3_series)
  * If a series has an episode airing within `config.sonarr[].series_scanner.hours_before_air`
    * default value of 4, max value of 12
  * OR
  * An episode that has aired previously
  * With a title of TBA (excluding specials)
    * will trigger a series refresh, to hopefully pull new info from The TVDB

This should prevent too many API calls to the TVDB, refreshing individual series, hourly

### Existing Renamer

This is basically the opposite functionality of the series scanner. This will check existing files for a `\bTBA\b` regex match, and if found, the file will be renamed

This app uses the [Sonarr API](https://sonarr.tv/docs/api/) to do the following

* Iterate over all [series](https://sonarr.tv/docs/api/#/Series/get_api_v3_series)
  * Ignores episodes that do not have files, or episodes that have TBA title
* Renames are batched up, per series
  * regex check on the episode filename
    * if filename matches `\bTBA\b`
    * then the file is added to current series batch rename
  * Once all episodes of a series have been checked, then episodes that matched the regex will be renamed via Sonarr

### Usage

The application run immediately on startup, and then continue to schedule jobs every hour (+- 5 minutes) after the first execution.

### Configuration

| Name                                       | Type    | Required | Default Value | Description                                                                            |
| ------------------------------------------ | ------- | -------- | ------------- | -------------------------------------------------------------------------------------- |
| `sonarr`                                   | Array   | Yes      | []            | One or more sonarr instances                                                           |
| `sonarr[].name`                            | string  | Yes      | N/A           | user friendly instance name, used in log messages                                      |
| `sonarr[].url`                             | string  | Yes      | N/A           | url for sonarr instance                                                                |
| `sonarr[].api_key`                         | string  | Yes      | N/A           | api_key for sonarr instance                                                            |
| `sonarr[].series_scanner.enabled`          | boolean | Yes      | N/A           | enables/disables series_scanner functionality                                          |
| `sonarr[].series_scanner.hourly_job`       | boolean | Yes      | N/A           | disables hourly job. App will exit after first execution                               |
| `sonarr[].series_scanner.hours_before_air` | integer | No       | 4             | The number of hours before an episode has aired, to trigger a rescan when title is TBA |
| `sonarr[].existing_renamer.enabled`        | boolean | Yes      | N/A           | enables/disables existing_renamer functionality                                        |
| `sonarr[].existing_renamer.hourly_job`     | boolean | Yes      | N/A           | disables hourly job. App will exit after first execution                               |
### Local Setup

#### devcontainer

There is a [devcontainer](https://containers.dev/) provided; it is optional but recommended.
[DevContainer's in VS Code](https://code.visualstudio.com/docs/devcontainers/containers)

####

You will need to create `config.yml` in the root of the repo, to mount your config within the devcontainer

```shell
$ poetry install

$ poetry run python src/main.py
```

#### Unit Tests
```shell
$ pytest --cov=src --cov-report=html tests --cov-branch
```
