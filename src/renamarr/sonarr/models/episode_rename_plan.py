from renamarr.sonarr.models.episode_rename import EpisodeRename


class SonarrEpisodeRenamePlan:
    """Plan for one Sonarr series episode file rename operation."""

    def __init__(self) -> None:
        self.files_to_rename: list[EpisodeRename] = []

    def has_episode_renames(self) -> bool:
        """Return whether any episode files need renames."""
        return len(self.files_to_rename) > 0

    def add_episode_file(
        self, file_id: int, season_number: int, episode_numbers: list[int]
    ) -> None:
        """Add an episode file to the pending series rename operation."""
        self.files_to_rename.append(
            EpisodeRename(file_id, season_number, episode_numbers)
        )

    def get_file_ids(self) -> list[int]:
        """Return file IDs for the Sonarr rename-files API call."""
        return [rename.file_id for rename in self.files_to_rename]

    def get_log_message(self) -> str:
        """Return formatted season/episode labels for logging."""
        episode_list = [
            f"S{str(rename.season_number).zfill(2)}E"
            + "-".join([str(episode).zfill(2) for episode in rename.episode_numbers])
            for rename in self.files_to_rename
        ]
        return ", ".join(episode_list)
