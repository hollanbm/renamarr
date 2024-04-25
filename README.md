# sonarr-series-scanner

## Requirements

* [Python 3.12](https://www.python.org/downloads/release/python-3123/)
* [pipx](https://pipx.pypa.io/stable/installation/)
* [poetry](https://python-poetry.org/docs/#installation)
* [Sonarr](https://sonarr.tv/)
 * This script is intended to be used alongside the `Episode Title Required` setting
   * Settings -> Media Management -> Episode Title Required -> `Always`

### The problem

It is relatively common for the TVDB to be updated the day of, or even after airing. Sonarr refreshes its TVDB cache every 24 hours.

Unfortunately, this can prevent import for up to 24 hours in extreme circumstances.

To solve this, I created this app

### How it works

This app uses the [Sonarr API](https://sonarr.tv/docs/api/) to do the following

* Iterate over continuing [series](https://sonarr.tv/docs/api/#/Series/get_api_v3_series)
  * If a series has grabbed an episode, with TBA title
    * will trigger a series refresh, to hopefully pull new info from The TVDB

This should prevent too many API calls to the TVDB, refreshing individual series, hourly

### Usage

The app will immediately exit upon completion. You will need to use cron or similar to handle scheduling. The recommended interval is one hour.

### Local Setup

#### devcontainer
There is a [devcontainer](https://containers.dev/) provided; it is optional but recommended.
[DevContainer's in VS Code](https://code.visualstudio.com/docs/devcontainers/containers)

#### 
```shell
poetry install

poetry run python src/main.py
```
