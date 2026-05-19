from types import SimpleNamespace
from unittest.mock import call

from pycliarr.api import RadarrCli

from radarr_renamarr import RadarrRenamarr


class TestRadarrRenamarr:
    def test_no_movies_returned(
        self, get_movie_empty, mock_loguru_info, mock_loguru_error, mocker
    ) -> None:
        rename_files = mocker.patch.object(RadarrCli, "rename_files")

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        mock_loguru_info.assert_has_calls(
            [call("Starting Renamarr"), call("Finished Renamarr")]
        )
        mock_loguru_error.assert_any_call("Radarr returned empty movie list")

        rename_files.assert_not_called()

    def test_when_movie_does_not_need_renamed(
        self, get_movie, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = []
        _sendCommand = mocker.patch.object(RadarrCli, "_sendCommand")

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        mock_loguru_debug.assert_any_call("Nothing to rename")
        _sendCommand.assert_not_called()

    def test_when_movie_need_renamed(self, get_movie, mocker) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = [
            dict(movieId=1, movieFileId=1)
        ]
        _sendCommand = mocker.patch.object(RadarrCli, "_sendCommand")

        rename_payload = dict(
            name="RenameFiles",
            files=[1],
            movieId=1,
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        _sendCommand.assert_called_once_with(rename_payload)

    def test_when_multiple_movies_need_renamed(self, get_movie, caplog, mocker) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = [
            dict(movieId=1, movieFileId=1),
            dict(movieId=1, movieFileId=2),
        ]
        _sendCommand = mocker.patch.object(RadarrCli, "_sendCommand")

        rename_payload1 = dict(
            name="RenameFiles",
            files=[1],
            movieId=1,
        )
        rename_payload2 = dict(
            name="RenameFiles",
            files=[2],
            movieId=1,
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=False).scan()

        _sendCommand.assert_has_calls([call(rename_payload1), call(rename_payload2)])

    def test_when_disk_scan_enabled_and_analyze_files_is_not(
        self, get_movie_empty, mock_loguru_warning, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = dict(
            enableMediaInfo=False
        )

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=True).scan()

        mock_loguru_warning.assert_called_once_with(
            "Analyse video files is not enabled, please enable setting, in order to use the reanalyze_files feature"
        )

    def test_when_disk_scan_enabled(
        self, get_movie_empty, mock_loguru_info, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = dict(
            enableMediaInfo=True
        )
        mocker.patch.object(RadarrCli, "_sendCommand").return_value = dict(id=1)
        mocker.patch.object(RadarrCli, "get_command").return_value = dict(
            status="completed", result="successful"
        )
        mocker.patch("radarr_renamarr.sleep").return_value = None

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=True).scan()

        assert call("Initiated disk scan of library") in mock_loguru_info.call_args_list
        assert (
            call("disk scan finished successfully") in mock_loguru_info.call_args_list
        )

    def test_when_disk_scan_enabled_and_fails(
        self, get_movie_empty, mock_loguru_info, mocker
    ) -> None:
        mocker.patch.object(RadarrCli, "request_get").return_value = dict(
            enableMediaInfo=True
        )
        mocker.patch.object(RadarrCli, "_sendCommand").return_value = dict(id=1)
        mocker.patch.object(RadarrCli, "get_command").return_value = dict(
            status="completed", result="failed"
        )
        mocker.patch("radarr_renamarr.sleep").return_value = None

        RadarrRenamarr("test", "test.tld", "test-api-key", analyze_files=True).scan()

        assert call("disk scan failed") in mock_loguru_info.call_args_list

    def test_rename_folders_disabled_skips_folder_rename_calls(
        self, get_movie, mocker
    ) -> None:
        request_get = mocker.patch.object(RadarrCli, "request_get", return_value=[])
        get_root_folder = mocker.patch.object(RadarrCli, "get_root_folder")
        request_put = mocker.patch.object(RadarrCli, "request_put")

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=False,
        ).scan()

        get_root_folder.assert_not_called()
        request_put.assert_not_called()
        request_get.assert_called_once_with(
            path="/api/v3/rename",
            url_params=dict(movieId=1),
        )

    def test_when_pending_movie_moves_processed(
        self, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        movie = SimpleNamespace(id=1, title="Movie", path="/root/OldName")
        mocker.patch.object(RadarrCli, "get_movie").return_value = [movie]
        mocker.patch.object(RadarrCli, "get_root_folder").return_value = [
            dict(path="/root")
        ]
        mocker.patch.object(RadarrCli, "request_get").side_effect = [
            dict(folder="NewName"),
            [],
        ]
        request_put = mocker.patch.object(RadarrCli, "request_put")
        mocker.patch.object(
            RadarrRenamarr, "_RadarrRenamarr__analyze_files", return_value=True
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        mock_loguru_debug.assert_any_call("Processing pending movie folder renames")
        request_put.assert_called_once_with(
            path="/api/v3/movie/editor",
            json_data=dict(rootFolderPath="/root", movieIds=[1], moveFiles=True),
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Starting Renamarr"),
                call("Renaming Movie folder for movie IDs: 1"),
                call("Movie folder rename successful for movie IDs: 1"),
                call("Initiated disk scan of library"),
                call("disk scan finished successfully"),
                call("Finished Renamarr"),
            ]
        )

    def test_when_pending_movie_moves_rescan_fails(
        self, mock_loguru_info, mocker
    ) -> None:
        movie = SimpleNamespace(id=1, title="Movie", path="/root/OldName")
        mocker.patch.object(RadarrCli, "get_movie").return_value = [movie]
        mocker.patch.object(RadarrCli, "get_root_folder").return_value = [
            dict(path="/root")
        ]
        mocker.patch.object(RadarrCli, "request_get").side_effect = [
            dict(folder="NewName"),
            [],
        ]
        mocker.patch.object(RadarrCli, "request_put")
        mocker.patch.object(
            RadarrRenamarr, "_RadarrRenamarr__analyze_files", return_value=False
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of library"),
                call("disk scan failed"),
            ]
        )

    def test_when_movie_folder_already_matches_no_bulk_move(
        self, mock_loguru_debug, mocker
    ) -> None:
        movie = SimpleNamespace(id=1, title="Movie", path="/root/Movie")
        mocker.patch.object(RadarrCli, "get_movie").return_value = [movie]
        mocker.patch.object(RadarrCli, "get_root_folder").return_value = [
            dict(path="/root")
        ]
        mocker.patch.object(RadarrCli, "request_get").side_effect = [
            dict(folder="Movie"),
            [],
        ]
        request_put = mocker.patch.object(RadarrCli, "request_put")

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        request_put.assert_not_called()
        assert (
            call("Processing pending movie folder renames")
            not in mock_loguru_debug.mock_calls
        )

    def test_when_multiple_movies_with_different_roots_are_processed(
        self, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        movie_a = SimpleNamespace(id=2, title="A Movie", path="/rootA/OldA")
        movie_b = SimpleNamespace(id=1, title="B Movie", path="/rootB/OldB")
        mocker.patch.object(RadarrCli, "get_movie").return_value = [movie_a, movie_b]
        mocker.patch.object(RadarrCli, "get_root_folder").return_value = [
            dict(path="/rootA"),
            dict(path="/rootB"),
        ]
        mocker.patch.object(RadarrCli, "request_get").side_effect = [
            dict(folder="NewA"),
            [],
            dict(folder="NewB"),
            [],
        ]
        request_put = mocker.patch.object(RadarrCli, "request_put")
        mocker.patch.object(
            RadarrRenamarr, "_RadarrRenamarr__analyze_files", return_value=True
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        mock_loguru_debug.assert_any_call("Processing pending movie folder renames")
        assert request_put.call_count == 2
        request_put.assert_has_calls(
            [
                call(
                    path="/api/v3/movie/editor",
                    json_data=dict(
                        rootFolderPath="/rootA", movieIds=[2], moveFiles=True
                    ),
                ),
                call(
                    path="/api/v3/movie/editor",
                    json_data=dict(
                        rootFolderPath="/rootB", movieIds=[1], moveFiles=True
                    ),
                ),
            ]
        )
        mock_loguru_info.assert_any_call(
            "Movie folder rename successful for movie IDs: 2"
        )
        mock_loguru_info.assert_any_call(
            "Movie folder rename successful for movie IDs: 1"
        )

    def test_when_root_folder_paths_overlap_uses_matching_root(
        self, mock_loguru_debug, mocker
    ) -> None:
        movie = SimpleNamespace(
            id=1,
            title="Anime Movie",
            path="/data/media/movies-anime/OldName",
        )
        mocker.patch.object(RadarrCli, "get_movie").return_value = [movie]
        mocker.patch.object(RadarrCli, "get_root_folder").return_value = [
            dict(path="/data/media/movies"),
            dict(path="/data/media/movies-anime"),
        ]
        mocker.patch.object(RadarrCli, "request_get").side_effect = [
            dict(folder="NewName"),
            [],
        ]
        request_put = mocker.patch.object(RadarrCli, "request_put")
        mocker.patch.object(
            RadarrRenamarr, "_RadarrRenamarr__analyze_files", return_value=True
        )

        RadarrRenamarr(
            "test",
            "test.tld",
            "test-api-key",
            analyze_files=False,
            rename_folders=True,
        ).scan()

        mock_loguru_debug.assert_any_call("Processing pending movie folder renames")
        request_put.assert_called_once_with(
            path="/api/v3/movie/editor",
            json_data=dict(
                rootFolderPath="/data/media/movies-anime",
                movieIds=[1],
                moveFiles=True,
            ),
        )
