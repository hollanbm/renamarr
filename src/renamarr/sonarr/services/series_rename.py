from loguru import logger
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.base_api import json_data

from renamarr.observability import (
    OperationName,
    OperationResult,
    ServiceName,
    get_observability,
)
from renamarr.sonarr.models.episode_rename_plan import SonarrEpisodeRenamePlan


class SeriesRename:
    """Service for renaming Sonarr episode files."""

    def __init__(self, sonarr_cli: SonarrCli, name: str = "") -> None:
        self.sonarr_cli = sonarr_cli
        self.name = name

    def process(self, series: list[SonarrSerieItem]) -> None:
        """Rename episode files for series with pending rename previews."""
        observability = get_observability()
        operation_result = OperationResult.FAILED
        with observability.start_span(
            "renamarr.sonarr.rename",
            attributes={
                "service": ServiceName.SONARR,
                "name": self.name,
                "operation": OperationName.RENAME,
            },
        ):
            try:
                observability.record_operation_scanned_items(
                    ServiceName.SONARR,
                    self.name,
                    OperationName.RENAME,
                    len(series),
                )
                found_candidates = False
                for show in series:
                    with logger.contextualize(item=show.title):
                        episodes_to_rename: list[json_data] = (
                            self.sonarr_cli.request_get(
                                path="/api/v3/rename",
                                url_params=dict(seriesId=show.id),
                            )
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
                            ServiceName.SONARR,
                            self.name,
                            OperationName.RENAME,
                            len(file_ids),
                        )
                        logger.info(f"Renaming {episode_rename_plan.get_log_message()}")
                        try:
                            self.sonarr_cli.rename_files(file_ids, show.id)
                        except Exception:
                            observability.record_operation_items(
                                ServiceName.SONARR,
                                self.name,
                                OperationName.RENAME,
                                OperationResult.FAILED,
                                len(file_ids),
                            )
                            raise
                        observability.record_operation_items(
                            ServiceName.SONARR,
                            self.name,
                            OperationName.RENAME,
                            OperationResult.ACCEPTED,
                            len(file_ids),
                        )
                operation_result = (
                    OperationResult.ACCEPTED
                    if found_candidates
                    else OperationResult.NOOP
                )
            finally:
                observability.record_operation_run(
                    ServiceName.SONARR,
                    self.name,
                    OperationName.RENAME,
                    operation_result,
                )
