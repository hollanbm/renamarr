from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from healthcheck import check_health, main
from renamarr.healthcheck.health_reporter import HealthReporter
from renamarr.healthcheck.health_state import HealthState

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def write_health(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def health_payload(
    state: object = HealthState.IDLE,
    heartbeat: object = 100.0,
    version: object = 1,
) -> dict[str, object]:
    return {"version": version, "state": state, "heartbeat": heartbeat}


def test_reporter_writes_initializing_state_atomically(tmp_path: Path) -> None:
    path = tmp_path / "health.json"

    HealthReporter(path=path, clock=lambda: 100.0)

    assert json.loads(path.read_text(encoding="utf-8")) == health_payload(
        state=HealthState.INITIALIZING
    )
    assert not (tmp_path / ".health.json.tmp").exists()


def test_reporter_throttles_idle_heartbeat(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    path = tmp_path / "health.json"
    clock = mocker.Mock(side_effect=[0.0, 1.0, 5.0, 11.0])
    reporter = HealthReporter(path=path, clock=clock, heartbeat_interval=10.0)
    reporter.idle()

    reporter.heartbeat()
    assert json.loads(path.read_text(encoding="utf-8"))["heartbeat"] == 1.0

    reporter.heartbeat()
    assert json.loads(path.read_text(encoding="utf-8")) == health_payload(
        heartbeat=11.0
    )


def test_running_job_starts_and_joins_heartbeat_thread(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    path = tmp_path / "health.json"
    thread = mocker.patch("renamarr.healthcheck.health_reporter.Thread")
    reporter = HealthReporter(path=path, clock=mocker.Mock(side_effect=[0.0, 1.0, 2.0]))

    with reporter.running_job():
        assert json.loads(path.read_text(encoding="utf-8"))["state"] == "running"

    thread.return_value.start.assert_called_once_with()
    thread.return_value.join.assert_called_once_with()
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "idle"


def test_running_job_returns_to_idle_after_exception(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    reporter = HealthReporter(path=path, heartbeat_interval=60.0)

    with pytest.raises(RuntimeError, match="job failed"), reporter.running_job():
        raise RuntimeError("job failed")

    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "idle"


def test_job_heartbeat_refreshes_until_stopped(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    path = tmp_path / "health.json"
    stopped = mocker.Mock()
    stopped.wait.side_effect = [False, True]
    reporter = HealthReporter(
        path=path,
        clock=mocker.Mock(side_effect=[0.0, 10.0]),
        heartbeat_interval=10.0,
    )

    reporter._heartbeat_until_stopped(stopped)

    assert json.loads(path.read_text(encoding="utf-8"))["heartbeat"] == 10.0
    assert stopped.wait.call_args_list == [mocker.call(10.0), mocker.call(10.0)]


@pytest.mark.parametrize("state", list(HealthState))
@pytest.mark.parametrize(
    ("heartbeat", "now", "expected"),
    [
        pytest.param(100.0, 100.0, True, id="current"),
        pytest.param(100.0, 130.0, True, id="maximum-age"),
        pytest.param(100.0, 130.1, False, id="stale"),
        pytest.param(100.0, 99.9, False, id="future"),
    ],
)
def test_check_health_validates_age_for_every_state(
    tmp_path: Path,
    state: HealthState,
    heartbeat: float,
    now: float,
    expected: bool,
) -> None:
    path = tmp_path / "health.json"
    write_health(path, health_payload(state=state, heartbeat=heartbeat))

    healthy, _ = check_health(path=path, clock=lambda: now)

    assert healthy is expected


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        pytest.param(None, "heartbeat is unavailable", id="missing"),
        pytest.param("{", "heartbeat is unavailable", id="malformed-json"),
        pytest.param("[]", "heartbeat schema is invalid", id="not-an-object"),
        pytest.param(
            '{"version":1,"state":"idle","heartbeat":100,"extra":true}',
            "heartbeat schema is invalid",
            id="unexpected-field",
        ),
    ],
)
def test_check_health_rejects_unavailable_or_invalid_schema(
    tmp_path: Path, contents: str | None, expected: str
) -> None:
    path = tmp_path / "health.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")

    assert check_health(path=path) == (False, expected)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            health_payload(version=True),
            "heartbeat version is unsupported",
            id="boolean-version",
        ),
        pytest.param(
            health_payload(version=2),
            "heartbeat version is unsupported",
            id="unsupported-version",
        ),
        pytest.param(
            health_payload(state="unknown"),
            "heartbeat state is invalid",
            id="unknown-state",
        ),
        pytest.param(
            health_payload(state=None),
            "heartbeat state is invalid",
            id="invalid-state-type",
        ),
        pytest.param(
            health_payload(heartbeat=True),
            "heartbeat timestamp is invalid",
            id="boolean-timestamp",
        ),
        pytest.param(
            health_payload(heartbeat="100"),
            "heartbeat timestamp is invalid",
            id="string-timestamp",
        ),
        pytest.param(
            health_payload(heartbeat=float("inf")),
            "heartbeat timestamp is invalid",
            id="infinite-timestamp",
        ),
    ],
)
def test_check_health_rejects_invalid_fields(
    tmp_path: Path, payload: dict[str, object], expected: str
) -> None:
    path = tmp_path / "health.json"
    write_health(path, payload)

    assert check_health(path=path, clock=lambda: 100.0) == (False, expected)


def test_main_returns_success_without_output(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch("healthcheck.check_health", return_value=(True, "healthy"))

    assert main() == 0
    assert capsys.readouterr().out == ""


def test_main_prints_failure(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    mocker.patch("healthcheck.check_health", return_value=(False, "heartbeat is stale"))

    assert main() == 1
    assert capsys.readouterr().out == "heartbeat is stale\n"
