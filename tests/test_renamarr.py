from collections.abc import Sequence
from unittest.mock import MagicMock, call

import pytest

from renamarr.exceptions import ArrOperationError
from renamarr.models import (
    CommandPollingSettings,
    CommandStatus,
    FileRenameBatch,
    FileRenameCandidate,
    FolderRenameBatch,
    MediaItem,
    ScanFailure,
    ScanPhase,
    ScanResult,
    WorkSummary,
)
from renamarr.protocols import ArrAdapter
from renamarr.renamarr import Renamarr


def configured_adapter(mocker, items: list[MediaItem]) -> MagicMock:
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


def test_folder_rename_batch_exposes_ids_and_titles() -> None:
    items = (
        MediaItem(1, "A", "/root/a"),
        MediaItem(2, "B", "/root/b"),
    )

    batch = FolderRenameBatch("/root", items)

    assert batch.item_ids == (1, 2)
    assert batch.titles == ("A", "B")


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param({"timeout_seconds": True}, id="boolean-timeout"),
        pytest.param({"timeout_seconds": 0}, id="non-positive-timeout"),
        pytest.param({"check_interval_seconds": False}, id="boolean-check-interval"),
        pytest.param({"check_interval_seconds": -1}, id="non-positive-check-interval"),
        pytest.param(
            {"timeout_seconds": 10, "check_interval_seconds": 11},
            id="check-exceeds-timeout",
        ),
    ],
)
def test_command_polling_settings_reject_invalid_values(
    settings: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        CommandPollingSettings(**settings)


def test_command_polling_settings_accept_valid_boundary() -> None:
    assert CommandPollingSettings(10, 10) == CommandPollingSettings(
        timeout_seconds=10,
        check_interval_seconds=10,
    )


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            ScanResult(0, WorkSummary(), WorkSummary(), WorkSummary(), ()),
            id="empty-library",
        ),
        pytest.param(
            ScanResult(
                1,
                WorkSummary(),
                WorkSummary(),
                WorkSummary(),
                (ScanFailure(ScanPhase.DISCOVERY, (), "failed"),),
            ),
            id="recorded-failure",
        ),
        pytest.param(
            ScanResult(1, WorkSummary(failed=1), WorkSummary(), WorkSummary(), ()),
            id="analysis-failure",
        ),
        pytest.param(
            ScanResult(1, WorkSummary(), WorkSummary(failed=1), WorkSummary(), ()),
            id="file-failure",
        ),
        pytest.param(
            ScanResult(1, WorkSummary(), WorkSummary(), WorkSummary(failed=1), ()),
            id="folder-failure",
        ),
    ],
)
def test_scan_result_reports_unsuccessful_outcomes(result: ScanResult) -> None:
    assert not result.successful


def test_scan_result_reports_success() -> None:
    result = ScanResult(
        1,
        WorkSummary(succeeded=1),
        WorkSummary(skipped=1),
        WorkSummary(skipped=1),
        (),
    )

    assert result.successful


def test_scan_runs_shared_workflow_in_sorted_order(
    mock_loguru_info: MagicMock, mocker
) -> None:
    item_b = MediaItem(2, "B", "/root/nested/old-b")
    item_a = MediaItem(1, "A", "/root/old-a")
    adapter = configured_adapter(mocker, [item_b, item_a])

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        rename_folders=True,
    ).scan()

    assert result == ScanResult(
        items_found=2,
        analysis=WorkSummary(succeeded=2),
        file_renames=WorkSummary(succeeded=2),
        folder_renames=WorkSummary(succeeded=2),
        failures=(),
    )
    assert result.successful
    assert [
        entry.args[0] for entry in adapter.get_file_rename_candidate.call_args_list
    ] == [
        item_a,
        item_b,
    ]
    adapter.move_folder.assert_has_calls(
        [
            call(FolderRenameBatch("/root", (item_a,))),
            call(FolderRenameBatch("/root/nested", (item_b,))),
        ]
    )
    assert mock_loguru_info.call_args_list[-1] == call(
        "Finished Renamarr successfully: items=2; "
        "analysis=2 succeeded, 0 failed, 0 skipped; "
        "file renames=2 succeeded, 0 failed, 0 skipped; "
        "folder renames=2 succeeded, 0 failed, 0 skipped"
    )


def test_scan_skips_disabled_analysis_and_folder_renames(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None

    result = Renamarr("test", adapter).scan()

    assert result.analysis == WorkSummary(skipped=1)
    assert result.file_renames == WorkSummary(skipped=1)
    assert result.folder_renames == WorkSummary(skipped=1)
    assert result.successful
    adapter.is_media_analysis_enabled.assert_not_called()
    adapter.list_root_folders.assert_not_called()


def test_scan_skips_analysis_disabled_by_service(mocker) -> None:
    items = [
        MediaItem(2, "Item B", "/root/Item B"),
        MediaItem(1, "Item A", "/root/Item A"),
    ]
    adapter = configured_adapter(mocker, items)
    adapter.is_media_analysis_enabled.return_value = False
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.analysis == WorkSummary(skipped=2)
    assert result.successful
    adapter.start_media_analysis.assert_not_called()


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
    mocker,
) -> None:
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


def test_scan_propagates_unexpected_discovery_error(mocker) -> None:
    adapter = configured_adapter(mocker, [])
    adapter.list_media_items.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        Renamarr("test", adapter).scan()


def test_analysis_failure_is_recorded_and_discovery_continues(mocker) -> None:
    items = [
        MediaItem(2, "Item B", "/root/Item B"),
        MediaItem(1, "Item A", "/root/Item A"),
    ]
    adapter = configured_adapter(mocker, items)
    adapter.is_media_analysis_enabled.side_effect = ArrOperationError("analysis failed")
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.items_found == 2
    assert result.analysis == WorkSummary(failed=2)
    assert result.failures == (
        ScanFailure(ScanPhase.ANALYSIS, (1, 2), "analysis failed"),
    )
    assert not result.successful


def test_completed_unsuccessful_analysis_command_is_recorded(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.return_value = CommandStatus(True, False)
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert result.failures[0] == ScanFailure(
        ScanPhase.ANALYSIS,
        (1,),
        "Media analysis command 10 completed unsuccessfully",
    )


def test_command_polling_checks_immediately_then_sleeps(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = [
        CommandStatus(False, False),
        CommandStatus(True, True),
    ]
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
    monotonic = mocker.patch(
        "renamarr.renamarr.time.monotonic", side_effect=[0.0, 0.0, 1.0]
    )
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 1),
    ).scan()

    assert result.analysis == WorkSummary(succeeded=1)
    adapter.get_command_status.assert_has_calls([call(10), call(10)])
    sleep.assert_called_once_with(1)
    assert monotonic.call_count == 3


def test_command_polling_times_out_before_sleep(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.return_value = CommandStatus(False, False)
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
    mocker.patch("renamarr.renamarr.time.monotonic", side_effect=[0.0, 10.0])
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 9),
    ).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert (
        "Timed out waiting for media analysis command 10" in result.failures[0].message
    )
    sleep.assert_not_called()


def test_command_polling_caps_sleep_at_remaining_timeout(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = [
        CommandStatus(False, False),
        CommandStatus(False, False),
        CommandStatus(False, False),
    ]
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
    mocker.patch(
        "renamarr.renamarr.time.monotonic",
        side_effect=[0.0, 0.0, 9.0, 9.0, 10.0, 10.0],
    )
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 9),
    ).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert sleep.call_args_list == [call(9), call(1)]


def test_command_polling_accepts_completion_on_final_deadline_check(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = [
        CommandStatus(False, False),
        CommandStatus(True, True),
    ]
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
    current_time = 0

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

    assert result.analysis == WorkSummary(succeeded=1)
    adapter.get_command_status.assert_has_calls([call(10), call(10)])
    sleep.assert_called_once_with(10)


def test_command_polling_rejects_check_after_deadline(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.return_value = CommandStatus(False, False)
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
    mocker.patch("renamarr.renamarr.time.monotonic", side_effect=[0.0, 0.0, 10.1])
    sleep = mocker.patch("renamarr.renamarr.time.sleep")

    result = Renamarr(
        "test",
        adapter,
        analyze_files=True,
        command_polling=CommandPollingSettings(10, 10),
    ).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert (
        "Timed out waiting for media analysis command 10" in result.failures[0].message
    )
    adapter.get_command_status.assert_called_once_with(10)
    sleep.assert_called_once_with(10)


def test_command_status_check_error_is_recorded(mocker) -> None:
    item = MediaItem(1, "Item", "/root/Item")
    adapter = configured_adapter(mocker, [item])
    adapter.get_command_status.side_effect = ArrOperationError("status check failed")
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None

    result = Renamarr("test", adapter, analyze_files=True).scan()

    assert result.analysis == WorkSummary(failed=1)
    assert result.failures[0].message == "status check failed"


def test_file_preview_failures_and_noops_do_not_block_other_items(mocker) -> None:
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

    result = Renamarr("test", adapter).scan()

    assert result.file_renames == WorkSummary(succeeded=1, failed=1, skipped=1)
    assert result.failures == (
        ScanFailure(ScanPhase.FILE_RENAMES, (1,), "preview failed"),
    )
    adapter.start_file_rename.assert_called_once()


def test_file_batch_planning_failure_marks_all_candidates_failed(mocker) -> None:
    items = [MediaItem(1, "A", "/root/A"), MediaItem(2, "B", "/root/B")]
    adapter = configured_adapter(mocker, items)
    adapter.build_file_rename_batches.side_effect = ArrOperationError("batch failed")

    result = Renamarr("test", adapter).scan()

    assert result.file_renames == WorkSummary(failed=2)
    assert result.failures == (
        ScanFailure(ScanPhase.FILE_RENAMES, (1, 2), "batch failed"),
    )
    adapter.start_file_rename.assert_not_called()


def test_invalid_file_batches_fail_before_starting_commands(mocker) -> None:
    item = MediaItem(1, "A", "/root/A")
    adapter = configured_adapter(mocker, [item])
    adapter.build_file_rename_batches.return_value = []
    adapter.build_file_rename_batches.side_effect = None

    with pytest.raises(ValueError, match="must contain every candidate exactly once"):
        Renamarr("test", adapter).scan()

    adapter.start_file_rename.assert_not_called()


def test_file_batch_failure_does_not_block_later_batches_or_folders(mocker) -> None:
    item_a = MediaItem(1, "A", "/root/old-a")
    item_b = MediaItem(2, "B", "/root/old-b")
    adapter = configured_adapter(mocker, [item_a, item_b])
    adapter.build_file_rename_batches.side_effect = None
    adapter.build_file_rename_batches.return_value = [
        FileRenameBatch((1,), (10,), "A"),
        FileRenameBatch((2,), (20,), "B"),
    ]
    adapter.start_file_rename.side_effect = [
        ArrOperationError("rename failed"),
        21,
    ]
    adapter.start_folder_rescan.side_effect = [30]

    result = Renamarr("test", adapter, rename_folders=True).scan()

    assert result.file_renames == WorkSummary(succeeded=1, failed=1)
    assert result.folder_renames == WorkSummary(succeeded=2)
    assert result.failures == (
        ScanFailure(ScanPhase.FILE_RENAMES, (1,), "rename failed"),
    )
    assert adapter.start_file_rename.call_count == 2
    adapter.move_folder.assert_called_once_with(
        FolderRenameBatch("/root", (item_a, item_b))
    )


def test_root_folder_listing_failure_marks_every_item_failed(mocker) -> None:
    items = [MediaItem(1, "A", "/root/A"), MediaItem(2, "B", "/root/B")]
    adapter = configured_adapter(mocker, items)
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
    adapter.list_root_folders.side_effect = ArrOperationError("roots failed")

    result = Renamarr("test", adapter, rename_folders=True).scan()

    assert result.folder_renames == WorkSummary(failed=2)
    assert result.failures == (
        ScanFailure(ScanPhase.FOLDER_RENAMES, (1, 2), "roots failed"),
    )


def test_folder_planning_isolated_failures_and_noops_continue(mocker) -> None:
    unmatched = MediaItem(1, "A", "/missing/A")
    lookup_failed = MediaItem(2, "B", "/root/B")
    correct = MediaItem(3, "C", "/root/C")
    renamed_a = MediaItem(4, "D", "/root/old-d")
    renamed_b = MediaItem(5, "E", "/root/old-e")
    items = [renamed_b, correct, unmatched, renamed_a, lookup_failed]
    adapter = configured_adapter(mocker, items)
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
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

    assert result.folder_renames == WorkSummary(succeeded=2, failed=2, skipped=1)
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


def test_failed_folder_operations_continue_across_roots(mocker) -> None:
    move_failed = MediaItem(1, "A", "/one/old-a")
    rescan_start_failed = MediaItem(2, "B", "/two/old-b")
    rescan_command_failed = MediaItem(3, "NASA", "/three/old-nasa")
    adapter = configured_adapter(
        mocker, [rescan_command_failed, rescan_start_failed, move_failed]
    )
    adapter.get_file_rename_candidate.return_value = None
    adapter.get_file_rename_candidate.side_effect = None
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
    assert [failure.message for failure in result.failures] == [
        "move failed",
        "rescan start failed",
        "Folder rescan: NASA command 33 completed unsuccessfully",
    ]
    assert adapter.start_folder_rescan.call_count == 2


def test_root_folder_matching_uses_components_and_deepest_match() -> None:
    nested_item = MediaItem(1, "Nested", "/data/media/tv/show")
    exact_item = MediaItem(2, "Exact", "/data/media/tv")
    overlapping_item = MediaItem(3, "Anime", "/data/media/tv-anime/show")
    roots = ["/data/media", "/data/media/tv", "/data/media/tv-anime"]

    assert Renamarr._find_root_folder(nested_item, roots) == "/data/media/tv"
    assert Renamarr._find_root_folder(exact_item, roots) == "/data/media/tv"
    assert Renamarr._find_root_folder(overlapping_item, roots) == "/data/media/tv-anime"
    assert Renamarr._find_root_folder(MediaItem(4, "None", "/other/x"), roots) is None
