from unittest.mock import call

from pycliarr.api import SonarrCli, SonarrSerieItem

from renamarr.sonarr.services.series_rename import SeriesRename


class TestSeriesRename:
    def test_process_skips_rename_when_no_episodes_need_rename(
        self, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series_a = SonarrSerieItem(id=1, title="Show A")
        series_b = SonarrSerieItem(id=2, title="Show B")
        request_get = mocker.patch.object(sonarr_cli, "request_get", return_value=[])
        rename_files = mocker.patch.object(sonarr_cli, "rename_files")

        SeriesRename(sonarr_cli).process([series_a, series_b])

        request_get.assert_has_calls(
            [
                call(path="/api/v3/rename", url_params=dict(seriesId=1)),
                call(path="/api/v3/rename", url_params=dict(seriesId=2)),
            ]
        )
        assert mock_loguru_debug.call_args_list == [
            call("No episodes to rename"),
            call("No episodes to rename"),
        ]
        rename_files.assert_not_called()

    def test_process_renames_episodes_per_series(
        self, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series = SonarrSerieItem(id=1, title="Show")
        mocker.patch.object(
            sonarr_cli,
            "request_get",
            return_value=[
                dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=10),
                dict(seasonNumber=1, episodeNumbers=[2], episodeFileId=20),
            ],
        )
        rename_files = mocker.patch.object(sonarr_cli, "rename_files")

        SeriesRename(sonarr_cli).process([series])

        mock_loguru_debug.assert_has_calls(
            [
                call("Found episodes to be renamed"),
                call("Found episodes to be renamed"),
            ]
        )
        mock_loguru_info.assert_called_once_with("Renaming S01E01, S01E02")
        rename_files.assert_called_once_with([10, 20], 1)

    def test_process_batches_each_series_independently(
        self, mock_loguru_info, mocker
    ) -> None:
        sonarr_cli = SonarrCli("test.tld", "test-api-key")
        series_a = SonarrSerieItem(id=1, title="Show A")
        series_b = SonarrSerieItem(id=2, title="Show B")
        mocker.patch.object(sonarr_cli, "request_get").side_effect = [
            [dict(seasonNumber=1, episodeNumbers=[1], episodeFileId=10)],
            [dict(seasonNumber=2, episodeNumbers=[1, 2], episodeFileId=20)],
        ]
        rename_files = mocker.patch.object(sonarr_cli, "rename_files")

        SeriesRename(sonarr_cli).process([series_a, series_b])

        mock_loguru_info.assert_has_calls(
            [
                call("Renaming S01E01"),
                call("Renaming S02E01-02"),
            ]
        )
        rename_files.assert_has_calls(
            [
                call([10], 1),
                call([20], 2),
            ]
        )
