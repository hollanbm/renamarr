# sonarr-series-scanner

## Requirements

This script is intended to be used alongside the `Episode Title Required` setting

* Settings
  * Media Management
    * Episode Title Required
      * Always

### The problem

It is fairly common for the TVDB to be updated the day of, or even after airing. Sonarr refreshes it's TVDB cache every 24 hours.

Unfortunately, in extreme circumstances, this can prevent import for up to 24 hours.

To solve this, I created this app

### How it works

This app uses the [Sonarr API](https://sonarr.tv/docs/api/) to do the following

* Iterate over continuing [series](https://sonarr.tv/docs/api/#/Series/get_api_v3_series)
  * If a series has grabbed episode, with TBA title
    * will trigger a series refresh, to hopefully pull new info from The TVDB

### Usage

The app will immediately exit upon completion. You will need to use cron or similar, to handle scheduling. Recomended interval is 1 hour.