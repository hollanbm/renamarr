from unittest.mock import call

from pycliarr.api import RadarrCli, RadarrMovieItem

from renamarr.radarr.services.renamarr import RadarrRenamarr


class TestRadarrRenamarr:
    def test_init_creates_trace_capable_client(self, mocker) -> None:
        radarr_cli = mocker.patch("renamarr.radarr.services.renamarr.create_radarr_cli")

        service = RadarrRenamarr("primary", "http://radarr", "secret")

        radarr_cli.assert_called_once_with("http://radarr", "secret", "primary")
        assert service.radarr_cli is radarr_cli.return_value

    def test_no_movies_returned(
        self, get_movie_empty, mock_loguru_info, mock_loguru_error, mocker
    ) -> None:
        analyze_files = mocker.patch("renamarr.radarr.services.renamarr.AnalyzeFiles")
        movie_rename = mocker.patch("renamarr.radarr.services.renamarr.MovieRename")
        movie_folder_rename = mocker.patch(
            "renamarr.radarr.services.renamarr.MovieFolderRename"
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        mock_loguru_info.assert_has_calls(
            [call("Starting Renamarr"), call("Finished Renamarr")]
        )
        mock_loguru_error.assert_any_call("Radarr returned empty movie list")
        analyze_files.assert_not_called()
        movie_rename.assert_not_called()
        movie_folder_rename.assert_not_called()

    def test_scan_sorts_movies_and_runs_movie_rename(
        self, mock_loguru_debug, mocker
    ) -> None:
        movie_b = RadarrMovieItem(id=2, title="B Movie")
        movie_a = RadarrMovieItem(id=1, title="A Movie")
        mocker.patch.object(RadarrCli, "get_movie").return_value = [movie_b, movie_a]
        analyze_files = mocker.patch("renamarr.radarr.services.renamarr.AnalyzeFiles")
        movie_rename = mocker.patch("renamarr.radarr.services.renamarr.MovieRename")
        movie_folder_rename = mocker.patch(
            "renamarr.radarr.services.renamarr.MovieFolderRename"
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        mock_loguru_debug.assert_any_call("Retrieved movie list")
        analyze_files.assert_not_called()
        movie_rename.return_value.process.assert_called_once_with([movie_a, movie_b])
        movie_folder_rename.assert_not_called()

    def test_scan_runs_folder_rename_when_enabled(self, get_movie, mocker) -> None:
        analyze_files = mocker.patch("renamarr.radarr.services.renamarr.AnalyzeFiles")
        movie_rename = mocker.patch("renamarr.radarr.services.renamarr.MovieRename")
        movie_folder_rename = mocker.patch(
            "renamarr.radarr.services.renamarr.MovieFolderRename"
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        analyze_files.assert_not_called()
        movie_rename.return_value.process.assert_called_once()
        movie_folder_rename.return_value.process.assert_called_once()

    def test_scan_runs_analyze_files_before_processing(self, get_movie, mocker) -> None:
        analyze_files = mocker.patch("renamarr.radarr.services.renamarr.AnalyzeFiles")
        movie_rename = mocker.patch("renamarr.radarr.services.renamarr.MovieRename")
        movie_folder_rename = mocker.patch(
            "renamarr.radarr.services.renamarr.MovieFolderRename"
        )
        events: list[str] = []
        analyze_files.return_value.process.side_effect = lambda: events.append(
            "analyze_files"
        )
        movie_rename.return_value.process.side_effect = lambda _: events.append(
            "movie_rename"
        )
        movie_folder_rename.return_value.process.side_effect = lambda _: events.append(
            "movie_folder_rename"
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=True,
        ).scan()

        assert events == [
            "analyze_files",
            "movie_rename",
            "movie_folder_rename",
        ]
        analyze_files.return_value.process.assert_called_once()
        movie_rename.return_value.process.assert_called_once()
        movie_folder_rename.return_value.process.assert_called_once()

    def test_scan_skips_post_analyze_when_folder_rename_is_disabled(
        self, get_movie, mocker
    ) -> None:
        analyze_files = mocker.patch("renamarr.radarr.services.renamarr.AnalyzeFiles")
        movie_rename = mocker.patch("renamarr.radarr.services.renamarr.MovieRename")
        movie_folder_rename = mocker.patch(
            "renamarr.radarr.services.renamarr.MovieFolderRename"
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=False,
        ).scan()

        analyze_files.return_value.process.assert_called_once()
        movie_rename.return_value.process.assert_called_once()
        movie_folder_rename.assert_not_called()

    def test_scan_with_analyze_files_returns_after_empty_movie_list(
        self, get_movie_empty, mocker
    ) -> None:
        analyze_files = mocker.patch("renamarr.radarr.services.renamarr.AnalyzeFiles")
        movie_rename = mocker.patch("renamarr.radarr.services.renamarr.MovieRename")
        movie_folder_rename = mocker.patch(
            "renamarr.radarr.services.renamarr.MovieFolderRename"
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=True,
            rename_folders=True,
        ).scan()

        analyze_files.return_value.process.assert_called_once()
        movie_rename.assert_not_called()
        movie_folder_rename.assert_not_called()
