import os, sys
from pycliarr.api import SonarrCli,CliServerError
from loguru import logger
#from dotenv import load_dotenv

#load_dotenv()

def series_scanner():
  sonarr_cli = SonarrCli(os.environ["SONARR_URL"], os.environ["SONARR_API_KEY"])

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

      # Filter episode list, so it only contains grabbed episodes, with TBA title
      episode_list[:] = [e for e in episode_list if e.get('title') == 'TBA' and e.get('grabbed')]

      if len(episode_list) > 0:
        logger.info(f'{show.title} - Found grabbed episode with TBA title')
        logger.info(f'{show.title} - Rescanning series')

        sonarr_cli.refresh_serie(show.id)
      else:
        logger.debug(f'{show.title} - No grabbed episodes with TBA title')

if __name__ == '__main__':
  if os.environ.get('SONARR_URL') is None:
    logger.error("SONARR_URL not set")
    exit(1)

  if os.environ.get('SONARR_API_KEY') is None:
    logger.error("SONARR_API_KEY not set")
    exit(1)

  try:
    series_scanner()
  except CliServerError as exc:
    logger.error(exc)
    exit(1)