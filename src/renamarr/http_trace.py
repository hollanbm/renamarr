import base64
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Literal, TypedDict

from loguru import logger
from pycliarr.api import RadarrCli, SonarrCli
from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter

type _TraceService = Literal["sonarr", "radarr"]

_REDACTED_HEADER_VALUE = "[REDACTED]"
_SENSITIVE_HEADERS = frozenset({"authorization", "x-api-key"})


class _TraceBody(TypedDict):
    encoding: Literal["utf-8", "base64"]
    content: str


class _TraceRequest(TypedDict):
    method: str
    url: str
    headers: dict[str, str]
    body: _TraceBody | None


class _TraceResponse(TypedDict):
    status_code: int
    reason: str | None
    headers: dict[str, str]
    body: _TraceBody | None


class _TraceError(TypedDict):
    type: str
    message: str


class _TraceRecord(TypedDict):
    schema_version: int
    timestamp: str
    duration_ms: float
    service: _TraceService
    instance: str
    request: _TraceRequest
    response: _TraceResponse | None
    error: _TraceError | None


def http_trace_enabled() -> bool:
    """Return whether HTTP tracing is enabled by the configured log level."""
    return os.getenv("LOG_LEVEL", "INFO").upper() == "TRACE"


def create_sonarr_cli(host_url: str, api_key: str, instance_name: str) -> SonarrCli:
    """Create a Sonarr client with HTTP tracing when TRACE logging is enabled."""
    if http_trace_enabled():
        return _TracedSonarrCli(host_url, api_key, instance_name)
    return SonarrCli(host_url, api_key)


def create_radarr_cli(host_url: str, api_key: str, instance_name: str) -> RadarrCli:
    """Create a Radarr client with HTTP tracing when TRACE logging is enabled."""
    if http_trace_enabled():
        return _TracedRadarrCli(host_url, api_key, instance_name)
    return RadarrCli(host_url, api_key)


def _sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: _REDACTED_HEADER_VALUE if name.casefold() in _SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }


def _serialize_body(body: object) -> _TraceBody | None:
    if body is None:
        return None
    if isinstance(body, str):
        if not body:
            return None
        return {"encoding": "utf-8", "content": body}
    if isinstance(body, bytes | bytearray | memoryview):
        body_bytes = bytes(body)
        if not body_bytes:
            return None
        try:
            return {"encoding": "utf-8", "content": body_bytes.decode("utf-8")}
        except UnicodeDecodeError:
            return {
                "encoding": "base64",
                "content": base64.b64encode(body_bytes).decode("ascii"),
            }
    raise TypeError(f"Unsupported HTTP body type: {type(body).__name__}")


def _serialize_request(request: PreparedRequest) -> _TraceRequest:
    return {
        "method": request.method or "",
        "url": request.url or "",
        "headers": _sanitize_headers(request.headers),
        "body": _serialize_body(request.body),
    }


def _serialize_reason(reason: str | bytes | None) -> str | None:
    if isinstance(reason, bytes):
        return reason.decode("latin-1")
    return reason


def _completed_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class _HttpTraceRecorder:
    def __init__(self, service: _TraceService, instance_name: str) -> None:
        self._service = service
        self._instance_name = instance_name

    def record_response(self, response: Response, **_: object) -> Response:
        try:
            record: _TraceRecord = {
                "schema_version": 1,
                "timestamp": _completed_timestamp(),
                "duration_ms": round(response.elapsed.total_seconds() * 1000, 3),
                "service": self._service,
                "instance": self._instance_name,
                "request": _serialize_request(response.request),
                "response": {
                    "status_code": response.status_code,
                    "reason": _serialize_reason(response.reason),
                    "headers": _sanitize_headers(response.headers),
                    "body": _serialize_body(response.content),
                },
                "error": None,
            }
            self._emit(record)
        except Exception as exc:
            self._warn(exc)
        return response

    def record_error(
        self,
        request: PreparedRequest,
        duration_ms: float,
        error: Exception,
    ) -> None:
        try:
            record: _TraceRecord = {
                "schema_version": 1,
                "timestamp": _completed_timestamp(),
                "duration_ms": round(duration_ms, 3),
                "service": self._service,
                "instance": self._instance_name,
                "request": _serialize_request(request),
                "response": None,
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
            }
            self._emit(record)
        except Exception as exc:
            self._warn(exc)

    def _emit(self, record: _TraceRecord) -> None:
        message = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        logger.bind(
            http_trace=True,
            service=self._service,
            instance=self._instance_name,
        ).log("TRACE", message)

    def _warn(self, error: Exception) -> None:
        logger.bind(service=self._service, instance=self._instance_name).warning(
            f"Unable to capture HTTP trace: {error}"
        )


class _HttpTraceAdapter(HTTPAdapter):
    def __init__(self, recorder: _HttpTraceRecorder) -> None:
        super().__init__()
        self._recorder = recorder

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        started_at = perf_counter()
        try:
            return super().send(request, **kwargs)
        except Exception as exc:
            self._recorder.record_error(
                request,
                duration_ms=(perf_counter() - started_at) * 1000,
                error=exc,
            )
            raise


def _configure_trace_session(session: Session, recorder: _HttpTraceRecorder) -> Session:
    session.hooks["response"].append(recorder.record_response)
    session.mount("http://", _HttpTraceAdapter(recorder))
    session.mount("https://", _HttpTraceAdapter(recorder))
    return session


class _TracedSonarrCli(SonarrCli):
    def __init__(self, host_url: str, api_key: str, instance_name: str) -> None:
        self._http_trace_recorder = _HttpTraceRecorder("sonarr", instance_name)
        super().__init__(host_url, api_key)

    def _build_session(self, username: str | None, password: str | None) -> Session:
        return _configure_trace_session(
            super()._build_session(username, password), self._http_trace_recorder
        )


class _TracedRadarrCli(RadarrCli):
    def __init__(self, host_url: str, api_key: str, instance_name: str) -> None:
        self._http_trace_recorder = _HttpTraceRecorder("radarr", instance_name)
        super().__init__(host_url, api_key)

    def _build_session(self, username: str | None, password: str | None) -> Session:
        return _configure_trace_session(
            super()._build_session(username, password), self._http_trace_recorder
        )
