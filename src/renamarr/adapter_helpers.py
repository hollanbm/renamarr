from collections.abc import Callable
from typing import Protocol

from pycliarr.api.base_api import json_data, json_dict

from renamarr.exceptions import ArrOperationError


class _CommandClient(Protocol):
    api_url_command: str

    def request_post(
        self, path: str, json_data: json_data | None = None
    ) -> json_data: ...


def _translate_api_error[Result, Error: Exception](
    service: str,
    caught_exception: type[Error],
    verb: str,
    target: str,
    action: Callable[[], Result],
) -> Result:
    try:
        return action()
    except caught_exception as error:
        raise ArrOperationError(f"{verb} {service} {target} failed: {error}") from error


def _as_dict(service: str, response: json_data) -> json_dict:
    if not isinstance(response, dict):
        raise TypeError(f"Expected an object response from {service}")
    return response


def _command_id(service: str, response: json_data) -> int:
    command_id = _as_dict(service, response)["id"]
    if not isinstance(command_id, int):
        raise TypeError(f"Expected a numeric command ID from {service}")
    return command_id


def _send_command(client: _CommandClient, payload: json_dict) -> json_data:
    return client.request_post(client.api_url_command, json_data=payload)
