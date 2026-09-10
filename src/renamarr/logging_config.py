import logging
import os
import re
import sys
import time
from contextlib import ExitStack
from datetime import time as DailyTime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import structlog
from opentelemetry.trace import get_current_span
from structlog.contextvars import bound_contextvars, get_contextvars
from structlog.typing import EventDict, Processor

from renamarr.telemetry import Telemetry, configure_telemetry

logger = structlog.stdlib.get_logger(__name__)


def _remove_formatter_fields(_: object, __: str, event_dict: EventDict) -> EventDict:
    event_dict.pop("message", None)
    event_dict.pop("asctime", None)
    return event_dict


class _RecordContext(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_contextvars().items():
            record.__dict__.setdefault(key, value)
        span = get_current_span().get_span_context()
        if span.is_valid:
            record.trace_id = f"{span.trace_id:032x}"
            record.span_id = f"{span.span_id:016x}"
        return True


class _InstanceFilter(logging.Filter):
    def __init__(self, arr_type: str, instance: str) -> None:
        super().__init__()
        self._arr_type = arr_type
        self._instance = instance

    def filter(self, record: logging.LogRecord) -> bool:
        return (
            record.__dict__.get("arr_type") == self._arr_type
            and record.__dict__.get("instance") == self._instance
        )


class _DailyFileHandler(TimedRotatingFileHandler):
    def __init__(self, path: Path, rotation: DailyTime, retention_days: int) -> None:
        super().__init__(path, when="midnight", atTime=rotation, encoding="utf-8")
        self._retention_seconds = retention_days * 86400
        self._archive_pattern = re.compile(
            rf"(?:{re.escape(path.name)}\.\d{{4}}-\d{{2}}-\d{{2}}"
            rf"|{re.escape(path.stem)}\.\d{{4}}-\d{{2}}-\d{{2}}_"
            rf"\d{{2}}-\d{{2}}-\d{{2}}_\d{{6}}(?:\.\d+)?"
            rf"{re.escape(path.suffix)})"
        )

    def doRollover(self) -> None:
        """Rotate the active file and remove this instance's expired archives."""
        super().doRollover()
        cutoff = time.time() - self._retention_seconds
        for archive in Path(self.baseFilename).parent.iterdir():
            if (
                self._archive_pattern.fullmatch(archive.name)
                and archive.is_file()
                and archive.stat().st_mtime <= cutoff
            ):
                archive.unlink()


class LoggingConfigurator:
    """Own Renamarr's local logging handlers and optional OTLP export."""

    def __init__(self) -> None:
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = logging.getLevelNamesMapping().get(level_name)
        if level is None or level == logging.NOTSET:
            raise ValueError(f"Unsupported LOG_LEVEL: {level_name!r}")
        self._log_level = level
        self._log_format = os.getenv("LOG_FORMAT", "text").lower()
        if self._log_format not in {"text", "json"}:
            raise ValueError("LOG_FORMAT must be 'text' or 'json'")
        self._handlers: list[logging.Handler] = []
        self._logger_levels: dict[logging.Logger, int] = {}
        self._stdout_handler: logging.Handler | None = None
        self._file_handlers: dict[tuple[str, str], logging.Handler] = {}
        self._telemetry: Telemetry | None = None

    def configure_stdout(self) -> None:
        """Configure structlog and the default stdout handler once."""
        if self._stdout_handler is not None:
            return
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.render_to_log_kwargs,
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=False,
        )
        root = logging.getLogger()
        application = logging.getLogger("renamarr")
        self._logger_levels = {root: root.level, application: application.level}
        root.setLevel(logging.WARNING)
        application.setLevel(self._log_level)
        handler = logging.StreamHandler(sys.stdout)
        self._configure_handler(handler, colors=sys.stdout.isatty())
        self._stdout_handler = handler

    def configure_otlp(self) -> None:
        """Attach opt-in OTLP export without changing local output."""
        if self._telemetry is not None:
            return
        telemetry = configure_telemetry(self._log_level)
        if telemetry is not None:
            telemetry.handler.addFilter(_RecordContext())
            logging.getLogger().addHandler(telemetry.handler)
            self._telemetry = telemetry

    def configure_instance_file(self, arr_type: str, instance_name: str) -> bool:
        """Add an instance's daily rotating file, returning whether it is usable."""
        instance_key = (arr_type, instance_name)
        if instance_key in self._file_handlers:
            return True
        rotation = os.getenv("LOG_ROTATION", "00:00")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", rotation):
            raise ValueError("LOG_ROTATION must be a daily time in HH:MM format")
        retention = re.fullmatch(
            r"([1-9]\d*) days?", os.getenv("LOG_RETENTION", "7 days")
        )
        if retention is None:
            raise ValueError("LOG_RETENTION must be a positive whole number of days")
        path = Path(os.getenv("LOG_DIR", "/logs")) / arr_type / f"{instance_name}.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = _DailyFileHandler(
                path, DailyTime.fromisoformat(rotation), int(retention[1])
            )
        except OSError as exc:
            with bound_contextvars(arr_type=arr_type, instance=instance_name):
                logger.warning(
                    "Unable to write log file; continuing with stdout logging only.",
                    path=str(path),
                    error=str(exc),
                )
            return False
        self._configure_handler(handler, colors=False)
        handler.addFilter(_InstanceFilter(arr_type, instance_name))
        self._file_handlers[instance_key] = handler
        return True

    def shutdown(self) -> None:
        """Drain OTLP once, then remove and close all owned local handlers."""
        root = logging.getLogger()
        with ExitStack() as cleanup:
            for configured_logger, level in self._logger_levels.items():
                cleanup.callback(configured_logger.setLevel, level)
            self._logger_levels.clear()
            for handler in self._handlers:
                cleanup.callback(handler.close)
                cleanup.callback(root.removeHandler, handler)
            self._handlers.clear()
            self._file_handlers.clear()
            self._stdout_handler = None
            telemetry, self._telemetry = self._telemetry, None
            if telemetry is not None:
                root.removeHandler(telemetry.handler)
                telemetry.shutdown()

    def _configure_handler(self, handler: logging.Handler, *, colors: bool) -> None:
        processors: list[Processor] = [
            structlog.stdlib.ExtraAdder(),
            _remove_formatter_fields,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
        ]
        if self._log_level == logging.DEBUG:
            processors.append(
                structlog.processors.CallsiteParameterAdder(
                    {
                        structlog.processors.CallsiteParameter.MODULE,
                        structlog.processors.CallsiteParameter.FUNC_NAME,
                        structlog.processors.CallsiteParameter.LINENO,
                    }
                )
            )
        renderers: list[Processor] = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
        ]
        if self._log_format == "json":
            renderers.extend(
                [
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ]
            )
        else:
            renderers.append(
                structlog.dev.ConsoleRenderer(
                    colors=colors, exception_formatter=structlog.dev.plain_traceback
                )
            )
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=processors, processors=renderers
            )
        )
        handler.addFilter(_RecordContext())
        handler.setLevel(self._log_level)
        logging.getLogger().addHandler(handler)
        self._handlers.append(handler)
