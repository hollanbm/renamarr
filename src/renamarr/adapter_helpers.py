from collections.abc import Callable

from renamarr.exceptions import ArrOperationError


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
