from dataclasses import dataclass
from typing import List


@dataclass()
class Move:
    """
    JSON payload for series editor endpoint, for renaming folders
    """

    rootFolderPath: str
    seriesIds: List[int]
    moveFiles: bool = True
