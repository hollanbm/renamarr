from typing import List

from models.rename import Rename


class BatchRename:
    def __init__(self):
        self.files_to_rename: List[Rename] = []

    def append(self, file_id, season_number, episode_numbers):
        self.files_to_rename.append(Rename(file_id, season_number, episode_numbers))

    def get_log_message(self) -> str:
        episode_list: List[str] = [
            f"S{str(rename.season_number).zfill(2)}E"
            + "-".join([str(ep).zfill(2) for ep in rename.episode_numbers])
            for rename in self.files_to_rename
        ]
        return ", ".join(episode_list)

    def get_file_ids(self) -> List[int]:
        return [rename.file_id for rename in self.files_to_rename]

    def has_files_to_rename(self) -> bool:
        return len(self.files_to_rename) > 0
