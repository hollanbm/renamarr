from dataclasses import dataclass

from pycliarr.api import SonarrSerieItem


@dataclass()
class SonarrRootMove:
    """
    Pending series editor operation, for renaming folders
    """

    rootFolderPath: str
    series: list[SonarrSerieItem]
    moveFiles: bool = True
