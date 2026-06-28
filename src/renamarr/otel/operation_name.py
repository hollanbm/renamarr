from enum import StrEnum


class OperationName(StrEnum):
    """Telemetry operation names."""

    RENAME = "rename"
    FOLDER_RENAME = "folder_rename"
    ANALYZE_FILES = "analyze_files"
