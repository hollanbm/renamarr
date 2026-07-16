from unittest.mock import call

from pycliarr.api import SonarrCli, SonarrSerieItem

from renamarr.sonarr.services.renamarr import SonarrRenamarr


class TestSonarrRenamarr:
    def test_init_creates_trace_capable_client(self, mocker) -> None:
        sonarr_cli = mocker.patch("renamarr.sonarr.services.renamarr.create_sonarr_cli")

        service = SonarrRenamarr("primary", "http://sonarr", "secret")

        sonarr_cli.assert_called_once_with("http://sonarr", "secret", "primary")
        assert service.sonarr_cli is sonarr_cli.return_value

    def test_no_series_returned(
        self, get_serie_empty, mock_loguru_info, mock_loguru_error, mocker
    ) -> None:
        analyze_files = mocker.patch("renamarr.sonarr.services.renamarr.AnalyzeFiles")
        series_rename = mocker.patch("renamarr.sonarr.services.renamarr.SeriesRename")
        series_folder_rename = mocker.patch(
            "renamarr.sonarr.services.renamarr.SeriesFolderRename"
        )

        SonarrRenamarr("test", "test.tld", "test-api-key").scan()

        mock_loguru_info.assert_has_calls(
            [call("Starting Renamarr"), call("Finished Renamarr")]
        )
        mock_loguru_error.assert_any_call("Sonarr returned empty series list")
        analyze_files.assert_not_called()
        series_rename.assert_not_called()
        series_folder_rename.assert_not_called()

    def test_scan_sorts_series_and_runs_series_rename(
        self, mock_loguru_debug, mocker
    ) -> None:
        series_b = SonarrSerieItem(id=2, title="B Show")
        series_a = SonarrSerieItem(id=1, title="A Show")
        mocker.patch.object(SonarrCli, "get_serie").return_value = [
            series_b,
            series_a,
        ]
        analyze_files = mocker.patch("renamarr.sonarr.services.renamarr.AnalyzeFiles")
        series_rename = mocker.patch("renamarr.sonarr.services.renamarr.SeriesRename")
        series_folder_rename = mocker.patch(
            "renamarr.sonarr.services.renamarr.SeriesFolderRename"
        )

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        mock_loguru_debug.assert_any_call("Retrieved series list")
        analyze_files.assert_not_called()
        series_rename.return_value.process.assert_called_once_with([series_a, series_b])
        series_folder_rename.assert_not_called()

    def test_scan_runs_folder_rename_when_enabled(self, get_serie, mocker) -> None:
        analyze_files = mocker.patch("renamarr.sonarr.services.renamarr.AnalyzeFiles")
        series_rename = mocker.patch("renamarr.sonarr.services.renamarr.SeriesRename")
        series_folder_rename = mocker.patch(
            "renamarr.sonarr.services.renamarr.SeriesFolderRename"
        )

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        analyze_files.assert_not_called()
        series_rename.return_value.process.assert_called_once()
        series_folder_rename.return_value.process.assert_called_once()

    def test_scan_runs_analyze_files_before_processing(self, get_serie, mocker) -> None:
        analyze_files = mocker.patch("renamarr.sonarr.services.renamarr.AnalyzeFiles")
        series_rename = mocker.patch("renamarr.sonarr.services.renamarr.SeriesRename")
        series_folder_rename = mocker.patch(
            "renamarr.sonarr.services.renamarr.SeriesFolderRename"
        )
        events: list[str] = []
        analyze_files.return_value.process.side_effect = lambda: events.append(
            "analyze_files"
        )
        series_rename.return_value.process.side_effect = lambda _: events.append(
            "series_rename"
        )
        series_folder_rename.return_value.process.side_effect = lambda _: events.append(
            "series_folder_rename"
        )

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=True,
        ).scan()

        assert events == [
            "analyze_files",
            "series_rename",
            "series_folder_rename",
        ]
        analyze_files.return_value.process.assert_called_once()
        series_rename.return_value.process.assert_called_once()
        series_folder_rename.return_value.process.assert_called_once()

    def test_scan_skips_folder_rename_when_disabled(self, get_serie, mocker) -> None:
        analyze_files = mocker.patch("renamarr.sonarr.services.renamarr.AnalyzeFiles")
        series_rename = mocker.patch("renamarr.sonarr.services.renamarr.SeriesRename")
        series_folder_rename = mocker.patch(
            "renamarr.sonarr.services.renamarr.SeriesFolderRename"
        )

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=False,
        ).scan()

        analyze_files.return_value.process.assert_called_once()
        series_rename.return_value.process.assert_called_once()
        series_folder_rename.assert_not_called()

    def test_scan_with_analyze_files_returns_after_empty_series_list(
        self, get_serie_empty, mocker
    ) -> None:
        analyze_files = mocker.patch("renamarr.sonarr.services.renamarr.AnalyzeFiles")
        series_rename = mocker.patch("renamarr.sonarr.services.renamarr.SeriesRename")
        series_folder_rename = mocker.patch(
            "renamarr.sonarr.services.renamarr.SeriesFolderRename"
        )

        SonarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=True,
        ).scan()

        analyze_files.return_value.process.assert_called_once()
        series_rename.assert_not_called()
        series_folder_rename.assert_not_called()
