from unittest.mock import call

from pycliarr.api import RadarrCli

from renamarr.radarr.services.analyze_files import AnalyzeFiles


class TestAnalyzeFiles:
    def test_process_logs_warning_when_media_info_analysis_is_disabled(
        self, mock_loguru_warning, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            radarr_cli, "request_get", return_value=dict(enableMediaInfo=False)
        )
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        AnalyzeFiles(radarr_cli).process()

        mock_loguru_warning.assert_called_once_with(
            "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
        )
        send_command.assert_not_called()

    def test_process_logs_success_when_rescan_succeeds(
        self, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            radarr_cli, "request_get", return_value=dict(enableMediaInfo=True)
        )
        mocker.patch.object(radarr_cli, "_sendCommand", return_value=dict(id=1))
        mocker.patch.object(
            radarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.radarr.services.analyze_files.sleep")

        AnalyzeFiles(radarr_cli).process()

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan finished successfully"),
            ]
        )

    def test_process_logs_failure_when_rescan_fails(
        self, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        mocker.patch.object(
            radarr_cli, "request_get", return_value=dict(enableMediaInfo=True)
        )
        mocker.patch.object(radarr_cli, "_sendCommand", return_value=dict(id=1))
        mocker.patch.object(
            radarr_cli,
            "get_command",
            return_value=dict(status="completed", result="failed"),
        )
        mocker.patch("renamarr.radarr.services.analyze_files.sleep")

        AnalyzeFiles(radarr_cli).process()

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan failed"),
            ]
        )
