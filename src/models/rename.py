from dataclasses import dataclass


@dataclass()
class Rename:
    file_id: int
    season_episode_number: str
