from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import call

import pytest
from pycliarr.api import SonarrCli, SonarrSerieItem
from pycliarr.api.exceptions import CliServerError

from renamarr.sonarr.services.series_folder_rename import (
    MAX_WAIT_SECONDS,
    SeriesFolderRename,
    SeriesRootFolderNotFoundError,
)

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestSeriesFolderRename:
    def test_process_skips_already_correct_series_folder(
        self, mock_loguru_debug: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Show")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[{"path": "/root"}]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "Show"})
        request_put = mocker.patch.object(sonarr_cli, "request_put")
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        SeriesFolderRename(sonarr_cli).process([series])

        request_put.assert_not_called()
        send_command.assert_not_called()
        assert (
            call("Processing pending series folder renames")
            not in mock_loguru_debug.mock_calls
        )

    def test_process_batches_and_rescans_when_rename_returns_json_lists(
        self,
        mock_loguru_info: MagicMock,
        mock_loguru_debug: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series_a = SonarrSerieItem(id=1, title="Show A", path="/rootA/OldA")
        series_b = SonarrSerieItem(id=2, title="Show B", path="/rootB/OldB")
        series_c = SonarrSerieItem(id=3, title="Show C", path="/rootA/OldC")
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[{"path": "/rootA"}, {"path": "/rootB"}],
        )
        mocker.patch.object(sonarr_cli, "request_get").side_effect = [
            {"folder": "NewA"},
            {"folder": "NewB"},
            {"folder": "NewC"},
        ]
        request_put = mocker.patch.object(
            sonarr_cli,
            "request_put",
            side_effect=[
                [{"id": 1}, {"id": 3}],
                [{"id": 2}],
            ],
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")
        send_command.side_effect = [{"id": 10}, {"id": 20}]
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            side_effect=[
                {"status": "completed", "result": "successful"},
                {"status": "completed", "result": "successful"},
            ],
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series_a, series_b, series_c])

        mock_loguru_debug.assert_any_call("Processing pending series folder renames")
        request_put.assert_has_calls(
            [
                call(
                    path="/api/v3/series/editor",
                    json_data={
                        "rootFolderPath": "/rootA",
                        "seriesIds": [1, 3],
                        "moveFiles": True,
                    },
                ),
                call(
                    path="/api/v3/series/editor",
                    json_data={
                        "rootFolderPath": "/rootB",
                        "seriesIds": [2],
                        "moveFiles": True,
                    },
                ),
            ]
        )
        get_command.assert_has_calls([call(cid=10), call(cid=20)])
        send_command.assert_has_calls(
            [
                call({"name": "RescanSeries", "priority": "high", "seriesIds": [1, 3]}),
                call({"name": "RescanSeries", "priority": "high", "seriesIds": [2]}),
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

    def test_process_sorts_root_folders_before_matching_series(
        self, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/rootA/Show")
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=[{"path": "/rootB"}, {"path": "/rootA"}],
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "Show"})
        service = SeriesFolderRename(sonarr_cli)
        find_series_root_folder = mocker.spy(
            service, "_SeriesFolderRename__find_series_root_folder"
        )

        service.process([series])

        assert find_series_root_folder.call_args.args[1] == [
            {"path": "/rootA"},
            {"path": "/rootB"},
        ]

    def test_process_logs_when_series_rescan_fails(
        self, mock_loguru_info: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[{"path": "/root"}]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "New"})
        mocker.patch.object(sonarr_cli, "request_put", return_value=[{"id": 1}])
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value={"id": 10})
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value={"status": "completed", "result": "failed"},
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
        self,
        mock_loguru_error: MagicMock,
        mock_loguru_info: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[{"path": "/root"}]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "New"})
        mocker.patch.object(sonarr_cli, "request_put", return_value=[{"id": 1}])
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value={"id": 10})
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value={"status": "started"},
        )
        sleep = mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")
        mocker.patch(
            "renamarr.sonarr.services.series_folder_rename.time.time",
            side_effect=[0, 0, MAX_WAIT_SECONDS],
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

    def test_process_propagates_folder_rename_server_error_without_rescan(
        self, mock_loguru_info: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[{"path": "/root"}]
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "New"})
        server_error = CliServerError(
            "Sonarr series folder rename failed",
            status_code=500,
            response="Internal Server Error",
        )
        mocker.patch.object(
            sonarr_cli,
            "request_put",
            side_effect=server_error,
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        with pytest.raises(CliServerError) as raised_error:
            SeriesFolderRename(sonarr_cli).process([series])

        assert raised_error.value is server_error
        send_command.assert_not_called()
        mock_loguru_info.assert_any_call("Renaming Series folder for: Show")
        assert (
            call("Series folder rename successful for series: Show")
            not in mock_loguru_info.mock_calls
        )
        assert (
            call("Initiated disk scan of updated series")
            not in mock_loguru_info.mock_calls
        )

    def test_process_logs_error_and_continues_after_series_without_matching_root_folder(
        self, mock_loguru_error: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        unmatched_series = SonarrSerieItem(
            id=1, title="Unmatched Show", path="/unmatched/Show"
        )
        matched_series = SonarrSerieItem(id=2, title="Matched Show", path="/root/Old")
        mocker.patch.object(
            sonarr_cli, "get_root_folder", return_value=[{"path": "/root"}]
        )
        request_get = mocker.patch.object(
            sonarr_cli, "request_get", return_value={"folder": "New"}
        )
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=[{"id": 2}]
        )
        send_command = mocker.patch.object(
            sonarr_cli, "_sendCommand", return_value={"id": 10}
        )
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value={"status": "completed", "result": "successful"},
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([unmatched_series, matched_series])

        mock_loguru_error.assert_called_once_with(
            "Unable to determine matching Sonarr root folder for series path /unmatched/Show"
        )
        request_get.assert_called_once_with(path="/api/v3/series/2/folder")
        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data={"rootFolderPath": "/root", "seriesIds": [2], "moveFiles": True},
        )
        send_command.assert_called_once_with(
            {"name": "RescanSeries", "priority": "high", "seriesIds": [2]}
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
                [{"path": "/root"}],
            )

    def test_process_uses_path_matching_for_overlapping_root_names(
        self, mock_loguru_debug: MagicMock, mocker: MockerFixture
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
                {"path": "/data/media/tv"},
                {"path": "/data/media/tv-anime"},
            ],
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "New"})
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=[{"id": 1}]
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value={"id": 10})
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value={"status": "completed", "result": "successful"},
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        mock_loguru_debug.assert_any_call("Processing pending series folder renames")
        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data={
                "rootFolderPath": "/data/media/tv-anime",
                "seriesIds": [1],
                "moveFiles": True,
            },
        )

    @pytest.mark.parametrize(
        ("series_path", "root_folders", "expected_root_folder"),
        [
            (
                "/data/media/tv/OldName",
                [{"path": "/data/media"}, {"path": "/data/media/tv"}],
                "/data/media/tv",
            ),
            (
                "/data/media/tv",
                [{"path": "/data/media"}, {"path": "/data/media/tv"}],
                "/data/media/tv",
            ),
        ],
        ids=["nested-roots", "root-equals-series-path"],
    )
    def test_process_uses_deepest_matching_root_folder(
        self,
        series_path: str,
        root_folders: list[dict[str, str]],
        expected_root_folder: str,
        mocker: MockerFixture,
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show", path=series_path)
        mocker.patch.object(
            sonarr_cli,
            "get_root_folder",
            return_value=root_folders,
        )
        mocker.patch.object(sonarr_cli, "request_get", return_value={"folder": "New"})
        request_put = mocker.patch.object(
            sonarr_cli, "request_put", return_value=[{"id": 1}]
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value={"id": 10})
        mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value={"status": "completed", "result": "successful"},
        )
        mocker.patch("renamarr.sonarr.services.series_folder_rename.sleep")

        SeriesFolderRename(sonarr_cli).process([series])

        request_put.assert_called_once_with(
            path="/api/v3/series/editor",
            json_data={
                "rootFolderPath": expected_root_folder,
                "seriesIds": [1],
                "moveFiles": True,
            },
        )
