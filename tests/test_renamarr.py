import logging
from collections.abc import Sequence
from unittest.mock import MagicMock, call

import pytest
from pytest_mock import MockerFixture
from structlog.contextvars import bound_contextvars, get_contextvars

from renamarr.exceptions import ArrOperationError
from renamarr.models.command import CommandPollingSettings, CommandStatus
from renamarr.models.media import (
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
)
from renamarr.models.scan import ScanFailure, ScanPhase, ScanResult, WorkSummary
from renamarr.protocols import ArrAdapter
from renamarr.renamarr import Renamarr


def configured_adapter(mocker: MockerFixture, items: list[MediaItem]) -> MagicMock:
    adapter = mocker.MagicMock(spec=ArrAdapter)
    adapter.list_media_items.return_value = items
    adapter.is_media_analysis_enabled.return_value = True
    adapter.start_media_analysis.return_value = 10
    adapter.get_command_status.return_value = CommandStatus(True, True)
    adapter.get_file_rename_candidate.side_effect = lambda item: FileRenameCandidate(
        item=item,
        file_ids=(item.id * 10,),
        description=item.title,
    )

    def build_file_rename_batches(
        candidates: Sequence[FileRenameCandidate],
    ) -> list[FileRenameBatch]:
        return [
            FileRenameBatch(
                item_ids=tuple(candidate.item.id for candidate in candidates),
                file_ids=tuple(
                    file_id
                    for candidate in candidates
                    for file_id in candidate.file_ids
                ),
                description=", ".join(
                    candidate.description for candidate in candidates
                ),
            )
        ]

    adapter.build_file_rename_batches.side_effect = build_file_rename_batches
    adapter.start_file_rename.return_value = 20
    adapter.list_root_folders.return_value = ["/root", "/root/nested", "/root-other"]
    adapter.get_expected_folder_name.side_effect = lambda item: (
        f"new-{item.title.lower()}"
    )
    adapter.start_folder_rescan.side_effect = [30, 31]
    return adapter


def without_file_renames(adapter: MagicMock) -> None:
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None


def test_scan_runs_shared_workflow_in_sorted_order(
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="renamarr")
    item_b = MediaItem(2, "B", "/root/nested/old-b")
    item_a = MediaItem(1, "A", "/root/old-a")
    adapter = configured_adapter(mocker, [item_b, item_a])
    candidate_a = FileRenameCandidate(item_a, (10,), "A")
    candidate_b = FileRenameCandidate(item_b, (20,), "B")
    file_batch = FileRenameBatch((1, 2), (10, 20), "A, B")
    folder_batch_a = FolderRenameBatch("/root", (item_a,))
    folder_batch_b = FolderRenameBatch("/root/nested", (item_b,))

    with bound_contextvars(arr_type="sonarr", instance="outer"):
        result = Renamarr(
            "test",
            adapter,
            analyze_files=True,
            rename_folders=True,
        ).scan()
        assert get_contextvars() == {"arr_type": "sonarr", "instance": "outer"}

    assert result == ScanResult(
        items_found=2,
        analysis=WorkSummary(success=2),
        file_renames=WorkSummary(success=2),
        folder_renames=WorkSummary(success=2),
        failures=(),
    )
    assert result.successful
    assert adapter.method_calls == [
        call.is_media_analysis_enabled(),
        call.start_media_analysis(),
        call.get_command_status(10),
        call.list_media_items(),
        call.get_file_rename_candidate(item_a),
        call.get_file_rename_candidate(item_b),
        call.build_file_rename_batches([candidate_a, candidate_b]),
        call.start_file_rename(file_batch),
        call.get_command_status(20),
        call.list_root_folders(),
        call.get_expected_folder_name(item_a),
        call.get_expected_folder_name(item_b),
        call.move_folder(folder_batch_a),
        call.start_folder_rescan(folder_batch_a),
        call.get_command_status(30),
        call.move_folder(folder_batch_b),
        call.start_folder_rescan(folder_batch_b),
        call.get_command_status(31),
    ]
    assert all(record.name == "renamarr.renamarr" for record in caplog.records)
    assert all(record.__dict__["arr_type"] == "sonarr" for record in caplog.records)
    assert all(record.__dict__["instance"] == "test" for record in caplog.records)
    assert all("item" not in record.__dict__ for record in caplog.records)
    assert get_contextvars() == {}
    file_events = [
        record
        for record in caplog.records
        if record.getMessage()
        in {"Renaming files", "File rename completed successfully"}
    ]
    assert len(file_events) == 2
    assert all(record.__dict__["description"] == "A, B" for record in file_events)
    assert all(record.__dict__["item_ids"] == (1, 2) for record in file_events)
    folder_events = [
        record
        for record in caplog.records
        if record.getMessage()
        in {"Renaming folders", "Folder workflow completed successfully"}
    ]
    assert [
        (
            record.__dict__["titles"],
            record.__dict__["item_ids"],
            record.__dict__["root_folder"],
        )
        for record in folder_events
    ] == [
        (("A",), (1,), "/root"),
        (("A",), (1,), "/root"),
        (("B",), (2,), "/root/nested"),
        (("B",), (2,), "/root/nested"),
    ]
    debug_summary, summary = caplog.records[-2:]
    assert debug_summary.levelno == logging.DEBUG
    assert debug_summary.getMessage() == "Items found"
    assert debug_summary.__dict__["items_found"] == 2
    assert debug_summary.__dict__["analysis_success"] == 2
    assert summary.levelno == logging.INFO
    assert summary.getMessage() == "Finished Renamarr successfully"
    expected_summary = {
        "items_found": 2,
        "analysis_success": 2,
        "analysis_failed": 0,
        "analysis_skipped": 0,
        "file_renames_success": 2,
        "file_renames_failed": 0,
        "file_renames_skipped": 0,
        "folder_renames_success": 2,
        "folder_renames_failed": 0,
        "folder_renames_skipped": 0,
        "failure_count": 0,
    }
    assert {key: summary.__dict__[key] for key in expected_summary} == expected_summary


def test_scan_skips_disabled_analysis_and_folder_renames(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.INFO, logger="renamarr")
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    without_file_renames(adapter)

    result = Renamarr("test", adapter).scan()

    assert result.analysis == WorkSummary(skipped=1)
    assert result.file_renames == WorkSummary(skipped=1)
    assert result.folder_renames == WorkSummary(skipped=1)
    assert result.successful
    adapter.is_media_analysis_enabled.assert_not_called()
    adapter.list_root_folders.assert_not_called()
    summary = caplog.records[-1]
    assert summary.levelno == logging.INFO
    assert summary.getMessage() == "Finished Renamarr successfully"
    assert summary.__dict__["analysis_skipped"] == 1
    assert summary.__dict__["file_renames_skipped"] == 1
    assert summary.__dict__["folder_renames_skipped"] == 1


def test_scan_skips_analysis_disabled_by_service(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="renamarr")
    items = [
        MediaItem(2, "Item B", "/root/Item B"),
        MediaItem(1, "Item A", "/root/Item A"),
    ]
    adapter = configured_adapter(mocker, items)
    adapter.is_media_analysis_enabled.return_value = False
    without_file_renames(adapter)

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.analysis == WorkSummary(skipped=2)
    assert result.successful
    adapter.start_media_analysis.assert_not_called()
    assert caplog.record_tuples == [
        (
            "renamarr.renamarr",
            logging.WARNING,
            "Media analysis is disabled in the Arr service",
        )
    ]


@pytest.mark.parametrize(
    ("library", "message"),
    [
        pytest.param(
            ArrOperationError("discovery failed"), "discovery failed", id="error"
        ),
        pytest.param([], "Media library is empty", id="empty"),
    ],
)
def test_scan_ends_after_library_discovery_failure(
    library: list[MediaItem] | ArrOperationError,
    message: str,
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="renamarr")
    adapter = configured_adapter(mocker, [])
    if isinstance(library, ArrOperationError):
        adapter.list_media_items.side_effect = library
    else:
        adapter.list_media_items.return_value = library

    result = Renamarr("test", adapter).scan()

    assert result.items_found == 0
    assert result.failures == (ScanFailure(ScanPhase.DISCOVERY, (), message),)
    assert not result.successful
    adapter.get_file_rename_candidate.assert_not_called()
    adapter.list_root_folders.assert_not_called()
    assert caplog.record_tuples == [
        ("renamarr.renamarr", logging.ERROR, message),
        ("renamarr.renamarr", logging.ERROR, "Finished Renamarr with failures"),
    ]
    failure, summary = caplog.records
    assert failure.__dict__["phase"] == "discovery"
    assert failure.__dict__["item_ids"] == ()
    assert summary.__dict__["items_found"] == 0
    assert summary.__dict__["failure_count"] == 1


@pytest.mark.parametrize(
    ("operation", "analyze_files", "rename_folders", "skip_file_renames"),
    [
        pytest.param("is_media_analysis_enabled", True, False, False, id="analysis"),
        pytest.param("list_media_items", False, False, False, id="discovery"),
        pytest.param(
            "get_file_rename_candidate", False, False, False, id="file-preview"
        ),
        pytest.param(
            "build_file_rename_batches", False, False, False, id="file-planning"
        ),
        pytest.param("start_file_rename", False, False, False, id="file-execution"),
        pytest.param("list_root_folders", False, True, True, id="folder-roots"),
        pytest.param(
            "get_expected_folder_name", False, True, True, id="folder-planning"
        ),
        pytest.param("move_folder", False, True, True, id="folder-execution"),
    ],
)
def test_scan_propagates_unexpected_adapter_errors(
    operation: str,
    analyze_files: bool,
    rename_folders: bool,
    skip_file_renames: bool,
    mocker: MockerFixture,
) -> None:
    item = MediaItem(1, "Item", "/root/old-item")
    adapter = configured_adapter(mocker, [item])
    if skip_file_renames:
        without_file_renames(adapter)
    getattr(adapter, operation).side_effect = RuntimeError("programming error")

    with bound_contextvars(arr_type="radarr", instance="outer", item="outer item"):
        with pytest.raises(RuntimeError, match="programming error"):
            Renamarr(
                "test",
                adapter,
                analyze_files=analyze_files,
                rename_folders=rename_folders,
            ).scan()
        assert get_contextvars() == {
            "arr_type": "radarr",
            "instance": "outer",
            "item": "outer item",
        }
    assert get_contextvars() == {}


def test_analysis_failure_is_recorded_and_discovery_continues(
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="renamarr")
    items = [
        MediaItem(2, "Item B", "/root/Item B"),
        MediaItem(1, "Item A", "/root/Item A"),
    ]
    adapter = configured_adapter(mocker, items)
    adapter.is_media_analysis_enabled.side_effect = ArrOperationError("analysis failed")
    without_file_renames(adapter)

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.items_found == 2
    assert result.analysis == WorkSummary(failed=2)
    assert result.failures == (
        ScanFailure(ScanPhase.ANALYSIS, (1, 2), "analysis failed"),
    )
    assert not result.successful
    debug_summary = caplog.records[-2]
    assert debug_summary.getMessage() == "Items found"
    assert debug_summary.__dict__["items_found"] == 2
    assert debug_summary.__dict__["analysis_failed"] == 2
    failures = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [record.getMessage() for record in failures] == [
        "analysis failed",
        "Finished Renamarr with failures",
    ]
    failure, summary = failures
    assert failure.__dict__["phase"] == "analysis"
    assert failure.__dict__["item_ids"] == (1, 2)
    assert summary.__dict__["analysis_failed"] == 2
    assert summary.__dict__["file_renames_skipped"] == 2
    assert summary.__dict__["folder_renames_skipped"] == 2
    assert summary.__dict__["failure_count"] == 1


def test_completed_unsuccessful_analysis_command_is_recorded(
    mocker: MockerFixture,
) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.return_value = CommandStatus(True, False)
    without_file_renames(adapter)

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert result.failures[0] == ScanFailure(
        ScanPhase.ANALYSIS,
        (1,),
        "Media analysis command 10 completed unsuccessfully",
    )


def test_command_polling_checks_immediately_then_sleeps(
    mocker: MockerFixture,
) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = [
        CommandStatus(False, False),
        CommandStatus(True, True),
    ]
    without_file_renames(adapter)
    monotonic = mocker.patch(
        "renamarr.renamarr.time.monotonic", side_effect=[1000.0, 1000.0, 1001.0]
    )
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 1),
    ).scan()

    assert result.analysis == WorkSummary(success=1)
    assert adapter.get_command_status.call_args_list == [call(10), call(10)]
    sleep.assert_called_once_with(1)
    assert monotonic.call_count == 3


def test_command_polling_times_out_before_sleep(mocker: MockerFixture) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.return_value = CommandStatus(False, False)
    without_file_renames(adapter)
    mocker.patch("renamarr.renamarr.time.monotonic", side_effect=[1000.0, 1010.0])
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 9),
    ).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert result.failures == (
        ScanFailure(
            ScanPhase.ANALYSIS,
            (1,),
            "Timed out waiting for media analysis command 10 after 10 seconds",
        ),
    )
    assert adapter.get_command_status.call_args_list == [call(10)]
    sleep.assert_not_called()


def test_command_polling_caps_sleep_at_remaining_timeout(
    mocker: MockerFixture,
) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = [
        CommandStatus(False, False),
        CommandStatus(False, False),
        CommandStatus(False, False),
    ]
    without_file_renames(adapter)
    mocker.patch(
        "renamarr.renamarr.time.monotonic",
        side_effect=[1000.0, 1000.0, 1009.0, 1009.0, 1010.0, 1010.0],
    )
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 9),
    ).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert adapter.get_command_status.call_args_list == [call(10), call(10), call(10)]
    assert sleep.call_args_list == [call(9), call(1)]


def test_command_polling_accepts_completion_on_final_deadline_check(
    mocker: MockerFixture,
) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = [
        CommandStatus(False, False),
        CommandStatus(True, True),
    ]
    without_file_renames(adapter)
    current_time = 1000

    def monotonic() -> int:
        return current_time

    def advance_time(seconds: int) -> None:
        nonlocal current_time
        current_time += seconds

    mocker.patch("renamarr.renamarr.time.monotonic", side_effect=monotonic)
    sleep = mocker.patch("renamarr.renamarr.time.sleep", side_effect=advance_time)

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 10),
    ).scan()

    assert result.analysis == WorkSummary(success=1)
    assert adapter.get_command_status.call_args_list == [call(10), call(10)]
    sleep.assert_called_once_with(10)


def test_command_polling_rejects_check_after_deadline(
    mocker: MockerFixture,
) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.return_value = CommandStatus(False, False)
    without_file_renames(adapter)
    mocker.patch(
        "renamarr.renamarr.time.monotonic", side_effect=[1000.0, 1000.0, 1010.1]
    )
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 10),
    ).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert result.failures == (
        ScanFailure(
            ScanPhase.ANALYSIS,
            (1,),
            "Timed out waiting for media analysis command 10 after 10 seconds",
        ),
    )
    assert adapter.get_command_status.call_args_list == [call(10)]
    sleep.assert_called_once_with(10)


def test_command_status_check_error_is_recorded(mocker: MockerFixture) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = ArrOperationError("status check failed")
    without_file_renames(adapter)

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert result.failures[0].message == "status check failed"


def test_file_preview_failures_and_noops_do_not_block_other_items(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="renamarr")
    failed = MediaItem(1, "A", "/root/A")
    skipped = MediaItem(2, "B", "/root/B")
    renamed = MediaItem(3, "C", "/root/C")
    adapter = configured_adapter(mocker, [renamed, skipped, failed])

    def preview(item: MediaItem) -> FileRenameCandidate | None:
        if item == failed:
            raise ArrOperationError("preview failed")
        if item == skipped:
            return None
        return FileRenameCandidate(item, (30,), item.title)

    adapter.get_file_rename_candidate.side_effect = preview

    with bound_contextvars(arr_type="sonarr"):
        result = Renamarr("test", adapter).scan()

    assert result.file_renames == WorkSummary(success=1, failed=1, skipped=1)
    assert result.failures == (
        ScanFailure(ScanPhase.FILE_RENAMES, (1,), "preview failed"),
    )
    adapter.start_file_rename.assert_called_once()
    failures = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [record.getMessage() for record in failures] == [
        "preview failed",
        "Finished Renamarr with failures",
    ]
    failure, summary = failures
    assert failure.__dict__["phase"] == "file_renames"
    assert failure.__dict__["item_ids"] == (1,)
    assert failure.__dict__["item"] == "A"
    skipped_event = next(
        record
        for record in caplog.records
        if record.getMessage() == "No files need renaming"
    )
    assert skipped_event.__dict__["item"] == "B"
    assert "item" not in summary.__dict__
    assert all(record.__dict__["arr_type"] == "sonarr" for record in caplog.records)
    assert summary.__dict__["file_renames_success"] == 1
    assert summary.__dict__["file_renames_failed"] == 1
    assert summary.__dict__["file_renames_skipped"] == 1
    assert summary.__dict__["folder_renames_skipped"] == 3
    assert summary.__dict__["failure_count"] == 1
    assert get_contextvars() == {}


def test_file_batch_planning_failure_marks_all_candidates_failed(
    mocker: MockerFixture,
) -> None:
    items = [MediaItem(1, "A", "/root/A"), MediaItem(2, "B", "/root/B")]
    adapter = configured_adapter(mocker, items)
    adapter.build_file_rename_batches.side_effect = ArrOperationError("batch failed")

    result = Renamarr("test", adapter).scan()

    assert result.file_renames == WorkSummary(failed=2)
    assert result.failures == (
        ScanFailure(ScanPhase.FILE_RENAMES, (1, 2), "batch failed"),
    )
    adapter.start_file_rename.assert_not_called()


@pytest.mark.parametrize(
    "batches",
    [
        pytest.param([FileRenameBatch((1,), (10,), "missing item")], id="missing-item"),
        pytest.param(
            [FileRenameBatch((1, 1, 2), (10, 10, 20), "duplicate item")],
            id="duplicate-item",
        ),
        pytest.param(
            [FileRenameBatch((1, 2, 3), (10, 20, 30), "extra item")],
            id="extra-item",
        ),
    ],
)
def test_invalid_file_batches_fail_before_starting_commands(
    batches: list[FileRenameBatch],
    mocker: MockerFixture,
) -> None:
    items = [MediaItem(1, "A", "/root/A"), MediaItem(2, "B", "/root/B")]
    adapter = configured_adapter(mocker, items)
    adapter.build_file_rename_batches.return_value = batches
    adapter.build_file_rename_batches.side_effect = None

    with pytest.raises(
        ValueError,
        match="^File rename batches must contain every candidate exactly once$",
    ):
        Renamarr("test", adapter).scan()

    adapter.start_file_rename.assert_not_called()
    adapter.get_command_status.assert_not_called()


def test_file_batch_failure_does_not_block_later_batches_or_folders(
    mocker: MockerFixture,
) -> None:
    item_a = MediaItem(1, "A", "/root/old-a")
    item_b = MediaItem(2, "B", "/root/old-b")
    adapter = configured_adapter(mocker, [item_a, item_b])
    file_batch_a = FileRenameBatch((1,), (10,), "A")
    file_batch_b = FileRenameBatch((2,), (20,), "B")
    folder_batch = FolderRenameBatch("/root", (item_a, item_b))
    adapter.build_file_rename_batches.side_effect = None
    adapter.build_file_rename_batches.return_value = [file_batch_a, file_batch_b]
    adapter.start_file_rename.side_effect = [
        ArrOperationError("rename failed"),
        21,
    ]
    adapter.start_folder_rescan.side_effect = [30]

    result = Renamarr("test", adapter, rename_folders=True).scan()

    assert result.file_renames == WorkSummary(success=1, failed=1)
    assert result.folder_renames == WorkSummary(success=2)
    assert result.failures == (
        ScanFailure(ScanPhase.FILE_RENAMES, (1,), "rename failed"),
    )
    assert adapter.start_file_rename.call_args_list == [
        call(file_batch_a),
        call(file_batch_b),
    ]
    assert adapter.move_folder.call_args_list == [call(folder_batch)]
    assert adapter.start_folder_rescan.call_args_list == [call(folder_batch)]
    assert adapter.get_command_status.call_args_list == [call(21), call(30)]


def test_root_folder_listing_failure_marks_every_item_failed(
    mocker: MockerFixture,
) -> None:
    items = [MediaItem(1, "A", "/root/A"), MediaItem(2, "B", "/root/B")]
    adapter = configured_adapter(mocker, items)
    without_file_renames(adapter)
    adapter.list_root_folders.side_effect = ArrOperationError("roots failed")

    result = Renamarr("test", adapter, rename_folders=True).scan()

    assert result.folder_renames == WorkSummary(failed=2)
    assert result.failures == (
        ScanFailure(ScanPhase.FOLDER_RENAMES, (1, 2), "roots failed"),
    )


def test_folder_planning_isolated_failures_and_noops_continue(
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="renamarr")
    unmatched = MediaItem(1, "A", "/missing/A")
    lookup_failed = MediaItem(2, "B", "/root/B")
    correct = MediaItem(3, "C", "/root/C")
    renamed_a = MediaItem(4, "D", "/root/old-d")
    renamed_b = MediaItem(5, "E", "/root/old-e")
    items = [renamed_b, correct, unmatched, renamed_a, lookup_failed]
    adapter = configured_adapter(mocker, items)
    without_file_renames(adapter)
    adapter.list_root_folders.return_value = ["/root"]

    def expected_folder(item: MediaItem) -> str:
        if item == lookup_failed:
            raise ArrOperationError("folder lookup failed")
        if item == correct:
            return "C"
        return f"new-{item.title.lower()}"

    adapter.get_expected_folder_name.side_effect = expected_folder
    adapter.start_folder_rescan.side_effect = None
    adapter.start_folder_rescan.return_value = 30

    result = Renamarr("test", adapter, rename_folders=True).scan()

    assert result.folder_renames == WorkSummary(success=2, failed=2, skipped=1)
    assert result.failures == (
        ScanFailure(
            ScanPhase.FOLDER_RENAMES,
            (1,),
            "No root folder matches media path /missing/A",
        ),
        ScanFailure(ScanPhase.FOLDER_RENAMES, (2,), "folder lookup failed"),
    )
    adapter.move_folder.assert_called_once_with(
        FolderRenameBatch("/root", (renamed_a, renamed_b))
    )
    failures = [
        record
        for record in caplog.records
        if record.__dict__.get("phase") == "folder_renames"
    ]
    assert [
        (record.__dict__["item"], record.__dict__["item_ids"]) for record in failures
    ] == [("A", (1,)), ("B", (2,))]
    skipped_event = next(
        record
        for record in caplog.records
        if record.getMessage() == "Media folder is already correctly named"
    )
    assert skipped_event.__dict__["item"] == "C"
    assert "item" not in caplog.records[-1].__dict__
    assert get_contextvars() == {}


def test_failed_folder_operations_continue_across_roots(
    mocker: MockerFixture,
) -> None:
    move_failed = MediaItem(1, "A", "/one/old-a")
    rescan_start_failed = MediaItem(2, "B", "/two/old-b")
    rescan_command_failed = MediaItem(3, "NASA", "/three/old-nasa")
    adapter = configured_adapter(
        mocker, [rescan_command_failed, rescan_start_failed, move_failed]
    )
    without_file_renames(adapter)
    adapter.list_root_folders.return_value = ["/one", "/two", "/three"]
    adapter.get_expected_folder_name.side_effect = lambda item: f"new-{item.title}"

    def move_folder(batch: FolderRenameBatch) -> None:
        if batch.root_folder_path == "/one":
            raise ArrOperationError("move failed")

    def start_rescan(batch: FolderRenameBatch) -> int:
        if batch.root_folder_path == "/two":
            raise ArrOperationError("rescan start failed")
        return 33

    adapter.move_folder.side_effect = move_folder
    adapter.start_folder_rescan.side_effect = start_rescan
    adapter.get_command_status.return_value = CommandStatus(True, False)

    result = Renamarr("test", adapter, rename_folders=True).scan()

    assert result.folder_renames == WorkSummary(failed=3)
    batch_one = FolderRenameBatch("/one", (move_failed,))
    batch_two = FolderRenameBatch("/two", (rescan_start_failed,))
    batch_three = FolderRenameBatch("/three", (rescan_command_failed,))
    assert result.failures == (
        ScanFailure(ScanPhase.FOLDER_RENAMES, (1,), "move failed"),
        ScanFailure(ScanPhase.FOLDER_RENAMES, (2,), "rescan start failed"),
        ScanFailure(
            ScanPhase.FOLDER_RENAMES,
            (3,),
            "Folder rescan: NASA command 33 completed unsuccessfully",
        ),
    )
    assert adapter.move_folder.call_args_list == [
        call(batch_one),
        call(batch_two),
        call(batch_three),
    ]
    assert adapter.start_folder_rescan.call_args_list == [
        call(batch_two),
        call(batch_three),
    ]
    assert adapter.get_command_status.call_args_list == [call(33)]


def test_root_folder_matching_uses_components_and_deepest_match() -> None:
    nested_item = MediaItem(1, "Nested", "/data/media/tv/show")
    exact_item = MediaItem(2, "Exact", "/data/media/tv")
    overlapping_item = MediaItem(3, "Anime", "/data/media/tv-anime/show")
    roots = ["/data/media", "/data/media/tv", "/data/media/tv-anime"]

    assert Renamarr._find_root_folder(nested_item, roots) == "/data/media/tv"
    assert Renamarr._find_root_folder(exact_item, roots) == "/data/media/tv"
    assert Renamarr._find_root_folder(overlapping_item, roots) == "/data/media/tv-anime"
    assert Renamarr._find_root_folder(MediaItem(4, "None", "/other/x"), roots) is None
