import os
from sys import stdout
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record


class LoggingConfigurator:
    """Configure Renamarr's Loguru sinks."""

    _LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level}</level> | "
        "{extra[instance]} | "
        "{extra[item_context]}"
        "<level>{message}</level>"
    )
    _DEBUG_LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[instance]} | "
        "{extra[item_context]}"
        "<level>{message}</level>"
    )

    def __init__(self) -> None:
        self._log_level = os.getenv("LOG_LEVEL", "INFO")
        self._logger_format = (
            self._DEBUG_LOG_FORMAT
            if self._log_level.upper() == "DEBUG"
            else self._LOG_FORMAT
        )

    def configure_stdout(self) -> None:
        """Configure the default stdout sink."""
        self._configure_records()
        logger.remove()
        logger.add(stdout, format=self._logger_format, level=self._log_level.upper())

    def configure_instance_file(self, service: str, instance_name: str) -> bool:
        """Configure a file sink for one service instance.

        Args:
            service: Service that owns the instance.
            instance_name: Instance whose records should be written to the sink.

        Returns:
            Whether the file sink was configured successfully.
        """
        self._configure_records()
        log_dir = os.getenv("LOG_DIR", "/logs")
        log_path = os.path.join(log_dir, service, f"{instance_name}.log")

        def matches_instance(record: Record) -> bool:
            return (
                record["extra"].get("service") == service
                and record["extra"].get("instance") == instance_name
            )

        try:
            logger.add(
                log_path,
                format=self._logger_format,
                level=os.getenv("LOG_LEVEL", "INFO"),
                rotation=os.getenv("LOG_ROTATION", "00:00"),
                retention=os.getenv("LOG_RETENTION", "7 days"),
                filter=matches_instance,
            )
        except OSError as exc:
            with logger.contextualize(service=service, instance=instance_name):
                logger.warning(
                    f"Unable to write logs to {log_path!r}; continuing with stdout logging only."
                )
                logger.warning(exc)
            return False
        return True

    def _configure_records(self) -> None:
        logger.configure(
            extra={"instance": "", "item": ""},
            patcher=self._set_item_context,
        )

    @staticmethod
    def _set_item_context(record: Record) -> None:
        item = record["extra"].get("item")
        record["extra"]["item_context"] = f"{item} | " if item else ""
