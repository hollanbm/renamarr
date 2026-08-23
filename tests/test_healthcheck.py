import json
from pathlib import Path

import pytest

from healthcheck import check_health, main
from renamarr.healthcheck.health_reporter import HealthReporter
from renamarr.healthcheck.health_state import HealthState


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


def test_reporter_preserves_health_file_when_temporary_write_fails(
    tmp_path: Path, mocker
) -> None:
    path = tmp_path / "health.json"
    reporter = HealthReporter(
        path=path,
        clock=mocker.Mock(side_effect=[100.0, 101.0]),
    )
    original_contents = path.read_text(encoding="utf-8")
    original_write_text = Path.write_text

    def write_partial_then_fail(target: Path, contents: str, *, encoding: str) -> int:
        original_write_text(target, contents[:1], encoding=encoding)
        raise OSError("interrupted write")

    mocker.patch.object(
        Path,
        "write_text",
        autospec=True,
        side_effect=write_partial_then_fail,
    )

    with pytest.raises(OSError, match="^interrupted write$"):
        reporter.idle()

    assert path.read_text(encoding="utf-8") == original_contents
    assert (tmp_path / ".health.json.tmp").read_text(encoding="utf-8") == "{"


def test_reporter_throttles_idle_heartbeat(tmp_path: Path, mocker) -> None:
    path = tmp_path / "health.json"
    clock = mocker.Mock(side_effect=[100.0, 101.0, 105.0, 111.0])
    reporter = HealthReporter(path=path, clock=clock, heartbeat_interval=10.0)
    reporter.idle()

    reporter.heartbeat()
    assert json.loads(path.read_text(encoding="utf-8"))["heartbeat"] == 101.0

    reporter.heartbeat()
    assert json.loads(path.read_text(encoding="utf-8")) == health_payload(
        heartbeat=111.0
    )


def test_running_job_starts_and_joins_heartbeat_thread(tmp_path: Path, mocker) -> None:
    path = tmp_path / "health.json"
    event_factory = mocker.patch(
        "renamarr.healthcheck.health_reporter.Event", autospec=True
    )
    thread_factory = mocker.patch(
        "renamarr.healthcheck.health_reporter.Thread", autospec=True
    )
    event = event_factory.return_value
    thread = thread_factory.return_value
    lifecycle: list[str] = []
    thread.start.side_effect = lambda: lifecycle.append("start")
    event.set.side_effect = lambda: lifecycle.append("stop")
    thread.join.side_effect = lambda: lifecycle.append("join")
    reporter = HealthReporter(
        path=path,
        clock=mocker.Mock(side_effect=[100.0, 101.0, 102.0]),
    )

    with reporter.running_job():
        assert json.loads(path.read_text(encoding="utf-8"))["state"] == "running"
        assert lifecycle == ["start"]

    event_factory.assert_called_once_with()
    thread_factory.assert_called_once_with(
        target=reporter._heartbeat_until_stopped,
        args=(event,),
        daemon=True,
        name="renamarr-heartbeat",
    )
    thread.start.assert_called_once_with()
    event.set.assert_called_once_with()
    thread.join.assert_called_once_with()
    assert lifecycle == ["start", "stop", "join"]
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "idle"


def test_running_job_returns_to_idle_after_exception(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    reporter = HealthReporter(path=path, heartbeat_interval=60.0)

    with pytest.raises(RuntimeError, match="job failed"), reporter.running_job():
        raise RuntimeError("job failed")

    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "idle"


def test_job_heartbeat_refreshes_until_stopped(tmp_path: Path, mocker) -> None:
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
        pytest.param(100.0, 100.0, (True, "healthy"), id="current"),
        pytest.param(100.0, 130.0, (True, "healthy"), id="maximum-age"),
        pytest.param(100.0, 130.1, (False, "heartbeat is stale"), id="stale"),
        pytest.param(100.0, 99.9, (False, "heartbeat is stale"), id="future"),
    ],
)
def test_check_health_validates_age_for_every_state(
    tmp_path: Path,
    state: HealthState,
    heartbeat: float,
    now: float,
    expected: tuple[bool, str],
) -> None:
    path = tmp_path / "health.json"
    write_health(path, health_payload(state=state, heartbeat=heartbeat))

    assert check_health(path=path, clock=lambda: now) == expected


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
        pytest.param(
            '{"state":"idle","heartbeat":100}',
            "heartbeat schema is invalid",
            id="missing-version",
        ),
        pytest.param(
            '{"version":1,"heartbeat":100}',
            "heartbeat schema is invalid",
            id="missing-state",
        ),
        pytest.param(
            '{"version":1,"state":"idle"}',
            "heartbeat schema is invalid",
            id="missing-heartbeat",
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


def test_main_returns_success_without_output(mocker, capsys) -> None:
    mocker.patch("healthcheck.check_health", return_value=(True, "healthy"))

    assert main() == 0
    assert capsys.readouterr().out == ""


def test_main_prints_failure(mocker, capsys) -> None:
    mocker.patch("healthcheck.check_health", return_value=(False, "heartbeat is stale"))

    assert main() == 1
    assert capsys.readouterr().out == "heartbeat is stale\n"
