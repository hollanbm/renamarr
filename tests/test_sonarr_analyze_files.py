from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import call

from pycliarr.api import SonarrCli

from renamarr.sonarr.services.analyze_files import AnalyzeFiles

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestAnalyzeFiles:
    def test_process_logs_warning_when_media_info_analysis_is_disabled(
        self, mock_loguru_warning: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            sonarr_cli, "request_get", return_value={"enableMediaInfo": False}
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        AnalyzeFiles(sonarr_cli).process()

        mock_loguru_warning.assert_called_once_with(
            "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
        )
        send_command.assert_not_called()

    def test_process_logs_success_when_rescan_succeeds(
        self, mock_loguru_info: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            sonarr_cli, "request_get", return_value={"enableMediaInfo": True}
        )
        send_command = mocker.patch.object(
            sonarr_cli, "_sendCommand", return_value={"id": 1}
        )
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            side_effect=[
                {"status": "started"},
                {"status": "completed", "result": "successful"},
            ],
        )
        sleep = mocker.patch("renamarr.sonarr.services.analyze_files.sleep")

        AnalyzeFiles(sonarr_cli).process()

        send_command.assert_called_once_with(
            {
                "name": "RescanSeries",
                "priority": "high",
            }
        )
        get_command.assert_has_calls([call(cid=1), call(cid=1)])
        assert sleep.call_count == 2
        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan finished successfully"),
            ]
        )

    def test_process_logs_failure_when_rescan_fails(
        self, mock_loguru_info: MagicMock, mocker: MockerFixture
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            sonarr_cli, "request_get", return_value={"enableMediaInfo": True}
        )
        send_command = mocker.patch.object(
            sonarr_cli, "_sendCommand", return_value={"id": 1}
        )
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value={"status": "completed", "result": "failed"},
        )
        sleep = mocker.patch("renamarr.sonarr.services.analyze_files.sleep")

        AnalyzeFiles(sonarr_cli).process()

        send_command.assert_called_once_with(
            {
                "name": "RescanSeries",
                "priority": "high",
            }
        )
        get_command.assert_called_once_with(cid=1)
        sleep.assert_called_once_with(10)
        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan failed"),
            ]
        )
