from dataclasses import dataclass
from typing import List


@dataclass()
class Rename:
    file_id: int
    season_number: int
    episode_numbers: List[int]
