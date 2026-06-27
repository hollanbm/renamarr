from loguru import logger
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data

from renamarr.observability import get_observability
from renamarr.sonarr.models.episode_rename_plan import SonarrEpisodeRenamePlan


class SeriesRename:
    """Service for renaming Sonarr episode files."""

    def __init__(self, sonarr_cli: SonarrCli, name: str = "") -> None:
        self.sonarr_cli = sonarr_cli
        self.name = name

    def process(self, series: list[SonarrSerieItem]) -> None:
        """Rename episode files for series with pending rename previews."""
        observability = get_observability()
        with observability.start_span(
            "renamarr.sonarr.rename",
            attributes={
                "service": "sonarr",
                "name": self.name,
                "operation": "rename",
            },
        ):
            observability.record_operation_scanned_items(
                "sonarr",
                self.name,
                "rename",
                len(series),
            )
            found_candidates = False
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

                    file_ids = episode_rename_plan.get_file_ids()
                    found_candidates = True
                    observability.record_operation_candidate_items(
                        "sonarr",
                        self.name,
                        "rename",
                        len(file_ids),
                    )
                    logger.info(f"Renaming {episode_rename_plan.get_log_message()}")
                    try:
                        self.sonarr_cli.rename_files(file_ids, show.id)
                    except Exception:
                        observability.record_operation_run(
                            "sonarr",
                            self.name,
                            "rename",
                            "failed",
                        )
                        observability.record_operation_items(
                            "sonarr",
                            self.name,
                            "rename",
                            "failed",
                            len(file_ids),
                        )
                        raise
                    observability.record_operation_items(
                        "sonarr",
                        self.name,
                        "rename",
                        "accepted",
                        len(file_ids),
                    )
            observability.record_operation_run(
                "sonarr",
                self.name,
                "rename",
                "accepted" if found_candidates else "noop",
            )
