from loguru import logger
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data

from renamarr.sonarr.models.episode_rename_plan import SonarrEpisodeRenamePlan


class SeriesRename:
    """Service for renaming Sonarr episode files."""

    def __init__(self, sonarr_cli: SonarrCli) -> None:
        self.sonarr_cli = sonarr_cli

    def process(self, series: list[SonarrSerieItem]) -> None:
        """Rename episode files for series with pending rename previews."""
        for show in series:
            with logger.contextualize(item=show.title):
                episodes_to_rename: list[json_data] = self.sonarr_cli.request_get(
                    path="/api/v3/rename",
                    url_params=dict(seriesId=show.id),
                )

                if len(episodes_to_rename) == 0:
                    logger.debug("No episodes to rename")
                    continue

                episode_rename_plan = SonarrEpisodeRenamePlan()
                for episode in episodes_to_rename:
                    logger.debug("Found episodes to be renamed")
                    episode_rename_plan.add_episode_file(
                        file_id=episode["episodeFileId"],
                        season_number=episode["seasonNumber"],
                        episode_numbers=episode["episodeNumbers"],
                    )

                logger.info(f"Renaming {episode_rename_plan.get_log_message()}")
                self.sonarr_cli.rename_files(
                    episode_rename_plan.get_file_ids(), show.id
                )
