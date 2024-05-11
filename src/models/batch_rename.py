from typing import List

from models.rename import Rename


class BatchRename:
    def __init__(self):
        self.files_to_rename = []

    def append(self, rename: Rename):
        self.files_to_rename.append(rename)

    def get_log_message(self) -> str:
        episode_list = [rename.season_episode_number for rename in self.files_to_rename]
        return ", ".join(episode_list)

    def get_file_ids(self) -> List[int]:
        return [rename.file_id for rename in self.files_to_rename]

    def has_files_to_rename(self) -> bool:
        return len(self.files_to_rename) > 0
