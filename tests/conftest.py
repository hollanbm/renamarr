import logging
from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def configure_test_logging(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
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
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="renamarr")
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
