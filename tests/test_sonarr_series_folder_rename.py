from pathlib import PurePosixPath
from unittest.mock import ANY, call

import pytest
from pycliarr.api import SonarrCli, SonarrSerieItem

from renamarr.otel.arr_command_result import ArrCommandResult
from renamarr.otel.operation_name import OperationName
from renamarr.otel.operation_result import OperationResult
from renamarr.otel.service_name import ServiceName
from renamarr.sonarr.services.series_folder_rename import (
    MAX_WAIT_SECONDS,
    SeriesFolderRename,
    SeriesRootFolderNotFoundError,
)


class TestSeriesFolderRename:
    def test_process_skips_already_correct_series_folder(
        self, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Show")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="Show"))
        request_put = mocker.patch.object(sonarr_cli, "request_put")
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        SeriesFolderRename(sonarr_cli).process([series])

        request_put.assert_not_called()
        send_command.assert_not_called()
        assert (
            call("Processing pending series folder renames")
            not in mock_loguru_debug.mock_calls
        )

    def test_process_batches_series_folder_renames_by_root(
        self, fake_observability, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series_a = SonarrSerieItem(id=1, title="Show A", path="/rootA/OldA")
        series_b = SonarrSerieItem(id=2, title="Show B", path="/rootB/OldB")
        series_c = SonarrSerieItem(id=3, title="Show C", path="/rootA/OldC")
        mocker.patch(
            "renamarr.sonarr.services.series_folder_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[dict(path="/rootA"), dict(path="/rootB")],
        )
        mocker.patch.object(sonarr_cli, "request_get").side_effect = [
            dict(folder="NewA"),
            dict(folder="NewB"),
            dict(folder="NewC"),
        ]
        request_put = mocker.patch.object(
            sonarr_cli,
            "request_put",
            side_effect=[mocker.Mock(status_code=200), mocker.Mock(status_code=299)],
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")
        send_command.side_effect = [dict(id=10), dict(id=20)]
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            side_effect=[
                dict(status="completed", result="successful"),
                dict(status="completed", result="successful"),
            ],
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli, name="tv").process(
            [series_a, series_b, series_c]
        )

        mock_loguru_debug.assert_any_call("Processing pending series folder renames")
        request_put.assert_has_calls(
            [
                call(
                    path="/api/v3/series/editor",
                    json_data=dict(
                        rootFolderPath="/rootA",
                        seriesIds=[1, 3],
                        moveFiles=True,
                    ),
                ),
                call(
                    path="/api/v3/series/editor",
                    json_data=dict(
                        rootFolderPath="/rootB",
                        seriesIds=[2],
                        moveFiles=True,
                    ),
                ),
            ]
        )
        get_command.assert_has_calls([call(cid=10), call(cid=20)])
        send_command.assert_has_calls(
            [
                call(dict(name="RescanSeries", priority="high", seriesIds=[1, 3])),
                call(dict(name="RescanSeries", priority="high", seriesIds=[2])),
            ]
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Renaming Series folders for: Show A, Show C"),
                call("Series folder rename successful for series: Show A, Show C"),
                call("Initiated disk scan of updated series"),
                call("disk scan finished successfully"),
                call("Renaming Series folder for: Show B"),
                call("Series folder rename successful for series: Show B"),
                call("Initiated disk scan of updated series"),
                call("disk scan finished successfully"),
            ]
        )
        fake_observability.start_span.assert_called_once_with(
            "renamarr.sonarr.folder_rename",
            attributes={
                "service": ServiceName.SONARR,
                "name": "tv",
                "operation": OperationName.FOLDER_RENAME,
            },
        )
        fake_observability.record_operation_items.assert_has_calls(
            [
                call(
                    ServiceName.SONARR,
                    "tv",
                    OperationName.FOLDER_RENAME,
                    OperationResult.ACCEPTED,
                    2,
                ),
                call(
                    ServiceName.SONARR,
                    "tv",
                    OperationName.FOLDER_RENAME,
                    OperationResult.ACCEPTED,
                    1,
                ),
            ]
        )
        fake_observability.record_operation_candidate_items.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            3,
        )
        fake_observability.record_operation_run.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            OperationResult.ACCEPTED,
        )
        assert fake_observability.record_arr_command.call_args_list == [
            call(
                ServiceName.SONARR,
                "tv",
                "RescanSeries",
                ArrCommandResult.SUCCESSFUL,
                ANY,
            ),
            call(
                ServiceName.SONARR,
                "tv",
                "RescanSeries",
                ArrCommandResult.SUCCESSFUL,
                ANY,
            ),
        ]

    def test_process_sorts_root_folders_before_matching_series(self, mocker) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/rootA/Show")
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[dict(path="/rootB"), dict(path="/rootA")],
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="Show"))
        service = SeriesFolderRename(sonarr_cli)
        find_series_root_folder = mocker.spy(
            service, "_SeriesFolderRename__find_series_root_folder"
        )

        service.process([series])

        assert find_series_root_folder.call_args.args[1] == [
            dict(path="/rootA"),
            dict(path="/rootB"),
        ]

    def test_process_logs_when_series_rescan_fails(
        self, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="failed"),
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of updated series"),
                call("disk scan failed"),
            ]
        )

    def test_process_logs_when_series_rescan_times_out(
        self, mock_loguru_error, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=10))
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="started"),
        )
        sleep = mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")
        mocker.patch(
            "renamarr.sonarr.services.series_folder_rename.time.time",
            side_effect=[0, 0, MAX_WAIT_SECONDS, MAX_WAIT_SECONDS],
        )

        SeriesFolderRename(sonarr_cli).process([series])

        get_command.assert_called_once_with(cid=10)
        sleep.assert_called_once_with(10)
        mock_loguru_error.assert_called_once_with(
            "Timed out waiting for Sonarr series rescan command 10 after 300 seconds"
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of updated series"),
                call("disk scan failed"),
            ]
        )

    def test_process_skips_rescan_when_folder_rename_status_is_unsuccessful(
        self, fake_observability, mock_loguru_error, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch(
            "renamarr.sonarr.services.series_folder_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=300)
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        SeriesFolderRename(sonarr_cli, name="tv").process([series])

        send_command.assert_not_called()
        mock_loguru_info.assert_any_call("Renaming Series folder for: Show")
        mock_loguru_error.assert_called_once_with(
            "Series folder rename failed for series: Show: status code 300"
        )
        assert (
            call("Series folder rename successful for series: Show")
            not in mock_loguru_info.mock_calls
        )
        assert (
            call("Initiated disk scan of updated series")
            not in mock_loguru_info.mock_calls
        )
        fake_observability.record_operation_items.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            OperationResult.FAILED,
            1,
        )
        fake_observability.record_operation_run.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            OperationResult.FAILED,
        )

    def test_process_records_failed_metric_when_folder_rename_request_fails(
        self, fake_observability, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch(
            "renamarr.sonarr.services.series_folder_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        exception = RuntimeError("BOOM!")
        mocker.patch.object(sonarr_cli, "request_put", side_effect=exception)

        with pytest.raises(RuntimeError) as excinfo:
            SeriesFolderRename(sonarr_cli, name="tv").process([series])

        assert excinfo.value is exception
        fake_observability.record_operation_run.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            OperationResult.FAILED,
        )
        fake_observability.record_operation_items.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            OperationResult.FAILED,
            1,
        )

    def test_process_records_failed_run_when_folder_rename_discovery_fails(
        self, fake_observability, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch(
            "renamarr.sonarr.services.series_folder_rename.get_observability",
            return_value=fake_observability,
        )
        exception = RuntimeError("BOOM!")
        mocker.patch.object(sonarr_cli, "get_root_folder", side_effect=exception)

        with pytest.raises(RuntimeError) as excinfo:
            SeriesFolderRename(sonarr_cli, name="tv").process([series])

        assert excinfo.value is exception
        fake_observability.record_operation_run.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            OperationName.FOLDER_RENAME,
            OperationResult.FAILED,
        )
        fake_observability.record_operation_candidate_items.assert_not_called()
        fake_observability.record_operation_items.assert_not_called()

    def test_process_logs_error_and_continues_after_series_without_matching_root_folder(
        self, mock_loguru_error, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        unmatched_series = SonarrSerieItem(
            id=1, title="Unmatched Show", path="/unmatched/Show"
        )
        matched_series = SonarrSerieItem(id=2, title="Matched Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        request_get = mocker.patch.object(
            sonarr_cli, "request_get", return_value=dict(folder="New")
        )
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        send_command = mocker.patch.object(
            sonarr_cli, "_sendCommand", return_value=dict(id=10)
        )
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([unmatched_series, matched_series])

        mock_loguru_error.assert_called_once_with(
            "Unable to determine matching Sonarr root folder for series path /unmatched/Show"
        )
        request_get.assert_called_once_with(path="/api/v3/series/2/folder")
        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data=dict(rootFolderPath="/root", seriesIds=[2], moveFiles=True),
        )
        send_command.assert_called_once_with(
            dict(name="RescanSeries", priority="high", seriesIds=[2])
        )

    def test_find_series_root_folder_raises_when_no_root_folder_matches(self) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        service = SeriesFolderRename(sonarr_cli)

        with pytest.raises(
            SeriesRootFolderNotFoundError,
            match=(
                "Unable to determine matching Sonarr root folder for series path "
                "/unmatched/Show"
            ),
        ):
            service._SeriesFolderRename__find_series_root_folder(
                PurePosixPath("/unmatched/Show"),
                [dict(path="/root")],
            )

    def test_process_uses_path_matching_for_overlapping_root_names(
        self, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(
            id=1,
            title="Anime Show",
            path="/data/media/tv-anime/OldName",
        )
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[
                dict(path="/data/media/tv"),
                dict(path="/data/media/tv-anime"),
            ],
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        mock_loguru_debug.assert_any_call("Processing pending series folder renames")
        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data=dict(
                rootFolderPath="/data/media/tv-anime",
                seriesIds=[1],
                moveFiles=True,
            ),
        )

    @pytest.mark.parametrize(
        ("series_path", "root_folders", "expected_root_folder"),
        [
            (
                "/data/media/tv/OldName",
                [dict(path="/data/media"), dict(path="/data/media/tv")],
                "/data/media/tv",
            ),
            (
                "/data/media/tv",
                [dict(path="/data/media"), dict(path="/data/media/tv")],
                "/data/media/tv",
            ),
        ],
        ids=["nested-roots", "root-equals-series-path"],
    )
    def test_process_uses_deepest_matching_root_folder(
        self,
        series_path,
        root_folders,
        expected_root_folder,
        mocker,
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path=series_path)
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=root_folders,
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value=dict(folder="New"))
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data=dict(
                rootFolderPath=expected_root_folder,
                seriesIds=[1],
                moveFiles=True,
            ),
        )
