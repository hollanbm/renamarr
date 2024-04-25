from pycliarr.api import SonarrCli
import os

from dotenv import load_dotenv
load_dotenv()

def series_scanner():
  sonarr_cli = SonarrCli(os.environ["SONARR_URL"], os.environ["SONARR_API_KEY"])

  series = sonarr_cli.get_serie()

  for show in series:
    if (show.status.lower() == "continuing" and 
        grabbed_episodes_without_name(sonarr_cli.get_episode(show.id))):
      sonarr_cli.refresh_serie(show.id)

def grabbed_episodes_without_name(episode_list):
  # Filter episode list, so it only contains episodes with an airDate, and no Title
  episode_list[:] = [d for d in episode_list if d.get('title') == 'TBA' and d.get('grabbed')]
  return len(episode_list) > 0
