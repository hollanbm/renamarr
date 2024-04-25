from os import environ
from datetime import datetime,timezone,timedelta
from dateutil import parser
from pycliarr.api import SonarrCli,CliServerError
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

def series_scanner():
  environ['LOGURU_LEVEL'] = 'INFO'
  sonarr_cli = SonarrCli(environ["SONARR_URL"], environ["SONARR_API_KEY"])

  series = sonarr_cli.get_serie()

  if series is []:
    logger.error("Sonarr returned empty series list")
    exit(0)
  else:
    logger.debug("Retrieved series list")

  for show in sorted(series, key=lambda s: s.title):
    if show.status.lower() == "continuing" :
      episode_list = sonarr_cli.get_episode(show.id)
      
      if episode_list is []:
        logger.error(f'{show.title} - Error fetching episode list')
        exit(1)
      else:
        logger.debug(f'{show.title} - Retrieved episode list')

      # Filter episode list, so it only contains episodes with TBA title
      episode_list[:] = [e for e in episode_list if e.get('seasonNumber') > 0 and e.get('title') == 'TBA' and e.get('airDateUtc') != None ]

      for episode in episode_list:
        air_date_utc = parser.parse(episode['airDateUtc']).astimezone(timezone.utc)
        hour_delta = (datetime.now(timezone.utc) - air_date_utc).total_seconds()/3600
        
        if -4 <= hour_delta < 0:
          logger.info(f'{show.title} - Found episode airing in the next 4 hours, with TBA title')
          logger.info(f'{show.title} - Rescanning series')

          sonarr_cli.refresh_serie(show.id)
          break
        elif hour_delta >= 0:
          logger.info(f'{show.title} - Found aired episode, with TBA title')
          logger.info(f'{show.title} - Rescanning series')

          sonarr_cli.refresh_serie(show.id)
          break
          

if __name__ == '__main__':
  if environ.get('SONARR_URL') is None:
    logger.error("SONARR_URL not set")
    exit(1)

  if environ.get('SONARR_API_KEY') is None:
    logger.error("SONARR_API_KEY not set")
    exit(1)

  try:
    series_scanner()
  except CliServerError as exc:
    logger.error(exc)
    exit(1)