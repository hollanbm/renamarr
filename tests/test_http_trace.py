import base64
import json
from datetime import timedelta

import pytest
from pycliarr.api import RadarrCli, SonarrCli
from requests import PreparedRequest, Request, Response
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout

from renamarr.http_trace import (
    _HttpTraceAdapter,
    _HttpTraceRecorder,
    _serialize_body,
    create_radarr_cli,
    create_sonarr_cli,
    http_trace_enabled,
)


def prepare_request(
    body: str | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> PreparedRequest:
    return Request(
        "POST",
        "http://sonarr:8989/api/v3/command",
        headers=headers,
        data=body,
    ).prepare()


def prepare_response(
    request: PreparedRequest,
    body: bytes = b'{"id":1}',
    status_code: int = 200,
) -> Response:
    response = Response()
    response.status_code = status_code
    response.reason = b"OK"
    response.headers = {
        "Content-Type": "application/json",
        "Authorization": "response-secret",
    }
    response._content = body
    response.request = request
    response.elapsed = timedelta(milliseconds=12.3456)
    return response


def emitted_record(bound_logger) -> dict[str, object]:
    level, message = bound_logger.log.call_args.args
    assert level == "TRACE"
    assert "\n" not in message
    return json.loads(message)


def test_http_trace_enabled_only_for_trace(mocker) -> None:
    mocker.patch.dict("os.environ", {"LOG_LEVEL": "trace"})
    assert http_trace_enabled()

    mocker.patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"})
    assert not http_trace_enabled()


def test_http_trace_enabled_defaults_to_false(mocker) -> None:
    mocker.patch.dict("os.environ", {}, clear=True)
    assert not http_trace_enabled()


def test_create_sonarr_cli_returns_native_client_without_trace(mocker) -> None:
    mocker.patch.dict("os.environ", {"LOG_LEVEL": "INFO"})

    client = create_sonarr_cli("http://sonarr", "secret", "primary")

    assert type(client) is SonarrCli
    client.close()


def test_create_radarr_cli_returns_native_client_without_trace(mocker) -> None:
    mocker.patch.dict("os.environ", {"LOG_LEVEL": "INFO"})

    client = create_radarr_cli("http://radarr", "secret", "primary")

    assert type(client) is RadarrCli
    client.close()


@pytest.mark.parametrize(
    ("factory", "url"),
    [
        (create_sonarr_cli, "http://sonarr"),
        (create_radarr_cli, "http://radarr"),
    ],
)
def test_trace_clients_configure_response_hooks_and_transport_adapters(
    factory, url, mocker
) -> None:
    mocker.patch.dict("os.environ", {"LOG_LEVEL": "TRACE"})

    client = factory(url, "secret", "primary")

    assert len(client._session.hooks["response"]) == 1
    assert isinstance(client._session.get_adapter("http://service"), _HttpTraceAdapter)
    assert isinstance(client._session.get_adapter("https://service"), _HttpTraceAdapter)
    client.close()


def test_record_response_emits_complete_sanitized_exchange(mocker) -> None:
    request = prepare_request(
        '{"name":"RenameFiles"}',
        {
            "authorization": "request-secret",
            "X-API-KEY": "api-secret",
            "Content-Type": "application/json",
        },
    )
    response = prepare_response(request)
    bound_logger = mocker.Mock()
    logger_bind = mocker.patch(
        "renamarr.http_trace.logger.bind", return_value=bound_logger
    )
    recorder = _HttpTraceRecorder("sonarr", "primary")

    returned_response = recorder.record_response(response, stream=False)

    assert returned_response is response
    logger_bind.assert_called_once_with(
        http_trace=True, service="sonarr", instance="primary"
    )
    record = emitted_record(bound_logger)
    assert record["schema_version"] == 1
    assert record["timestamp"].endswith("Z")
    assert record["duration_ms"] == 12.346
    assert record["service"] == "sonarr"
    assert record["instance"] == "primary"
    assert record["request"] == {
        "method": "POST",
        "url": "http://sonarr:8989/api/v3/command",
        "headers": {
            "authorization": "[REDACTED]",
            "X-API-KEY": "[REDACTED]",
            "Content-Type": "application/json",
            "Content-Length": "22",
        },
        "body": {"encoding": "utf-8", "content": '{"name":"RenameFiles"}'},
    }
    assert record["response"] == {
        "status_code": 200,
        "reason": "OK",
        "headers": {
            "Content-Type": "application/json",
            "Authorization": "[REDACTED]",
        },
        "body": {"encoding": "utf-8", "content": '{"id":1}'},
    }
    assert record["error"] is None


def test_record_response_emits_each_redirect_exchange(mocker) -> None:
    bound_logger = mocker.Mock()
    mocker.patch("renamarr.http_trace.logger.bind", return_value=bound_logger)
    recorder = _HttpTraceRecorder("radarr", "primary")
    redirect_request = prepare_request()
    redirected_request = Request("GET", "https://radarr/api/v3/movie").prepare()
    redirect_response = prepare_response(redirect_request, status_code=302)
    redirect_response.reason = "Found"

    recorder.record_response(redirect_response)
    recorder.record_response(prepare_response(redirected_request))

    assert bound_logger.log.call_count == 2


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, None),
        ("", None),
        (b"", None),
        ("plain text", {"encoding": "utf-8", "content": "plain text"}),
        (bytearray(b"bytes"), {"encoding": "utf-8", "content": "bytes"}),
        (memoryview(b"view"), {"encoding": "utf-8", "content": "view"}),
        (
            b"\xff\x00",
            {
                "encoding": "base64",
                "content": base64.b64encode(b"\xff\x00").decode("ascii"),
            },
        ),
    ],
)
def test_serialize_body(body, expected) -> None:
    assert _serialize_body(body) == expected


def test_serialize_body_rejects_streaming_body() -> None:
    with pytest.raises(TypeError, match="Unsupported HTTP body type: object"):
        _serialize_body(object())


def test_record_response_failure_warns_and_preserves_response(mocker) -> None:
    request = prepare_request()
    request.body = object()
    response = prepare_response(request)
    bound_logger = mocker.Mock()
    logger_bind = mocker.patch(
        "renamarr.http_trace.logger.bind", return_value=bound_logger
    )

    returned_response = _HttpTraceRecorder("sonarr", "primary").record_response(
        response
    )

    assert returned_response is response
    logger_bind.assert_called_once_with(service="sonarr", instance="primary")
    bound_logger.warning.assert_called_once_with(
        "Unable to capture HTTP trace: Unsupported HTTP body type: object"
    )


def test_record_error_emits_request_and_exception(mocker) -> None:
    request = prepare_request(b"payload", {"X-Api-Key": "secret"})
    bound_logger = mocker.Mock()
    mocker.patch("renamarr.http_trace.logger.bind", return_value=bound_logger)
    recorder = _HttpTraceRecorder("radarr", "primary")

    recorder.record_error(request, 123.4567, ConnectTimeout("timed out"))

    record = emitted_record(bound_logger)
    assert record["duration_ms"] == 123.457
    assert record["request"]["headers"]["X-Api-Key"] == "[REDACTED]"
    assert record["response"] is None
    assert record["error"] == {"type": "ConnectTimeout", "message": "timed out"}


def test_record_error_failure_warns_without_raising(mocker) -> None:
    request = prepare_request()
    request.body = object()
    bound_logger = mocker.Mock()
    logger_bind = mocker.patch(
        "renamarr.http_trace.logger.bind", return_value=bound_logger
    )

    _HttpTraceRecorder("radarr", "primary").record_error(
        request, 1, ConnectTimeout("timed out")
    )

    logger_bind.assert_called_once_with(service="radarr", instance="primary")
    bound_logger.warning.assert_called_once()


def test_trace_adapter_returns_successful_response(mocker) -> None:
    request = prepare_request()
    response = prepare_response(request)
    recorder = mocker.Mock()
    mocker.patch.object(HTTPAdapter, "send", return_value=response)
    adapter = _HttpTraceAdapter(recorder)

    returned_response = adapter.send(request, stream=False)

    assert returned_response is response
    recorder.record_error.assert_not_called()


def test_trace_adapter_records_and_reraises_transport_failure(mocker) -> None:
    request = prepare_request()
    error = ConnectTimeout("timed out")
    recorder = mocker.Mock()
    mocker.patch.object(HTTPAdapter, "send", side_effect=error)
    mocker.patch("renamarr.http_trace.perf_counter", side_effect=[1.0, 1.125])
    adapter = _HttpTraceAdapter(recorder)

    with pytest.raises(ConnectTimeout, match="timed out"):
        adapter.send(request, stream=False)

    recorder.record_error.assert_called_once_with(
        request, duration_ms=125.0, error=error
    )
