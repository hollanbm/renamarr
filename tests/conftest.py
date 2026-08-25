from unittest.mock import MagicMock

import pytest
from loguru import logger
from pytest_mock import MockerFixture


@pytest.fixture
def mock_loguru_error(mocker) -> None:
    return mocker.patch.object(logger, "error")


@pytest.fixture
def mock_loguru_debug(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "debug")


@pytest.fixture
def mock_loguru_info(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "info")


@pytest.fixture
def mock_loguru_warning(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(logger, "warning")
