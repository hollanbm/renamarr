from dataclasses import dataclass


@dataclass()
class EpisodeRename:
    """Episode file rename preview returned by Sonarr."""

    file_id: int
    season_number: int
    episode_numbers: list[int]
