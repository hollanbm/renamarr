from unittest.mock import ANY, call

from pycliarr.api import SonarrCli

from renamarr.otel.arr_command_result import ArrCommandResult
from renamarr.otel.service_name import ServiceName
from renamarr.sonarr.services.analyze_files import AnalyzeFiles


class TestAnalyzeFiles:
    def test_process_logs_warning_when_media_info_analysis_is_disabled(
        self, mock_loguru_warning, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            sonarr_cli, "request_get", return_value=dict(enableMediaInfo=False)
        )
        send_command = mocker.patch.object(sonarr_cli, "_sendCommand")

        AnalyzeFiles(sonarr_cli).process()

        mock_loguru_warning.assert_called_once_with(
            "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
        )
        send_command.assert_not_called()

    def test_process_logs_success_when_rescan_succeeds(
        self, fake_observability, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch(
            "renamarr.sonarr.services.analyze_files.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            sonarr_cli, "request_get", return_value=dict(enableMediaInfo=True)
        )
        send_command = mocker.patch.object(
            sonarr_cli, "_sendCommand", return_value=dict(id=1)
        )
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            side_effect=[
                dict(status="started"),
                dict(status="completed", result="successful"),
            ],
        )
        sleep = mocker.patch("renamarr.sonarr.services.analyze_files.sleep")

        AnalyzeFiles(sonarr_cli, name="tv").process()

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
        fake_observability.record_arr_command.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            "RescanSeries",
            ArrCommandResult.SUCCESSFUL,
            ANY,
        )

    def test_process_logs_failure_when_rescan_fails(
        self, fake_observability, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch(
            "renamarr.sonarr.services.analyze_files.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            sonarr_cli, "request_get", return_value=dict(enableMediaInfo=True)
        )
        send_command = mocker.patch.object(
            sonarr_cli, "_sendCommand", return_value=dict(id=1)
        )
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="completed", result="failed"),
        )
        sleep = mocker.patch("renamarr.sonarr.services.analyze_files.sleep")

        AnalyzeFiles(sonarr_cli, name="tv").process()

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
        fake_observability.record_arr_command.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            "RescanSeries",
            ArrCommandResult.FAILED,
            ANY,
        )

    def test_process_logs_failure_and_records_timeout_when_rescan_times_out(
        self, fake_observability, mock_loguru_error, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        mocker.patch(
            "renamarr.sonarr.services.analyze_files.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            sonarr_cli, "request_get", return_value=dict(enableMediaInfo=True)
        )
        mocker.patch.object(sonarr_cli, "_sendCommand", return_value=dict(id=1))
        get_command = mocker.patch.object(
            sonarr_cli,
            "get_command",
            return_value=dict(status="started"),
        )
        sleep = mocker.patch("renamarr.sonarr.services.analyze_files.sleep")
        mocker.patch(
            "renamarr.sonarr.services.analyze_files.time.time",
            side_effect=[0, 0, 300, 300],
        )

        AnalyzeFiles(sonarr_cli, name="tv").process()

        get_command.assert_called_once_with(cid=1)
        sleep.assert_called_once_with(10)
        mock_loguru_error.assert_called_once_with(
            "Timed out waiting for Sonarr analyze files command 1 after 300 seconds"
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan failed"),
            ]
        )
        fake_observability.record_arr_command.assert_called_once_with(
            ServiceName.SONARR,
            "tv",
            "RescanSeries",
            ArrCommandResult.TIMEOUT,
            300,
        )
