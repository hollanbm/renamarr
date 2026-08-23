from collections.abc import Callable
from typing import Protocol

from pycliarr.api.base_api import json_data, json_dict

from renamarr.exceptions import ArrOperationError


class _CommandClient(Protocol):
    api_url_command: str

    def request_post(
        self, path: str, json_data: json_data | None = None
    ) -> json_data: ...


def translate_api_error[Result, Error: Exception](
    service: str,
    caught_exception: type[Error],
    verb: str,
    target: str,
    action: Callable[[], Result],
) -> Result:
    """Run an API action and translate expected client errors."""
    try:
        return action()
    except caught_exception as error:
        raise ArrOperationError(f"{verb} {service} {target} failed: {error}") from error


def as_dict(service: str, response: json_data) -> json_dict:
    """Return an API response as an object."""
    if not isinstance(response, dict):
        raise TypeError(f"Expected an object response from {service}")
    return response


def command_id(service: str, response: json_data) -> int:
    """Return the numeric command ID from an API response."""
    response_command_id = as_dict(service, response).get("id")
    if not isinstance(response_command_id, int):
        raise TypeError(f"Expected a numeric command ID from {service}")
    return response_command_id


def send_command(client: _CommandClient, payload: json_dict) -> json_data:
    """Post a command payload to a client's command endpoint."""
    return client.request_post(client.api_url_command, json_data=payload)
