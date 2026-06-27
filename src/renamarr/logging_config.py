import os
from sys import stdout

from loguru import logger

from renamarr.observability import enrich_log_record_with_trace, is_otel_enabled


class LoggingConfigurator:
    """Configure Renamarr Loguru sinks."""

    _LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level}</level> | "
        "{extra[instance]} | "
        "{extra[item]} | "
        "<level>{message}</level>"
    )
    _DEBUG_LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[instance]} | "
        "{extra[item]} | "
        "<level>{message}</level>"
    )
    _TRACE_LOG_FORMAT = "trace_id={extra[trace_id]} | span_id={extra[span_id]} | "

    def configure_stdout(self) -> None:
        """Configure the default stdout sink."""
        otel_enabled = is_otel_enabled()
        logger.configure(
            extra={
                "service": "",
                "instance": "",
                "item": "",
                "trace_id": "",
                "span_id": "",
            },
            patcher=enrich_log_record_with_trace if otel_enabled else None,
        )
        logger.remove()
        logger.add(stdout, **self._logger_options(otel_enabled))

    def configure_instance_file(self, service: str, instance_name: str) -> bool:
        """Configure a file sink for a service instance."""
        log_dir = os.getenv("LOG_DIR", "/logs")
        log_path = os.path.join(log_dir, service, f"{instance_name}.log")
        try:
            logger.add(
                log_path,
                **self._logger_options(is_otel_enabled()),
                rotation=os.getenv("LOG_ROTATION", "00:00"),
                retention=os.getenv("LOG_RETENTION", "7 days"),
                filter=lambda record, configured_service=service, configured_name=instance_name: (
                    record["extra"].get("service") == configured_service
                    and record["extra"].get("instance") == configured_name
                ),
            )
        except OSError as exc:
            with logger.contextualize(service=service, instance=instance_name):
                logger.warning(
                    f"Unable to write logs to {log_path!r}; continuing with stdout logging only."
                )
                logger.warning(exc)
            return False
        return True

    def _logger_options(self, otel_enabled: bool) -> dict[str, object]:
        log_level = os.getenv("LOG_LEVEL", "INFO")
        if os.getenv("LOG_FORMAT", "text").lower() == "json":
            return {"level": log_level, "serialize": True}
        return {
            "format": self._logger_format(log_level, otel_enabled),
            "level": log_level,
        }

    def _logger_format(self, log_level: str, otel_enabled: bool) -> str:
        base_logger_format = (
            self._DEBUG_LOG_FORMAT if log_level.upper() == "DEBUG" else self._LOG_FORMAT
        )
        if not otel_enabled:
            return base_logger_format
        return base_logger_format.replace(
            "<level>{message}</level>",
            f"{self._TRACE_LOG_FORMAT}<level>{{message}}</level>",
        )
