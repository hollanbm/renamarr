from unittest.mock import call

import pytest
from pycliarr.api import RadarrCli, RadarrMovieItem

from renamarr.radarr.services.movie_folder_rename import MovieFolderRename


class TestMovieFolderRename:
    def test_process_skips_already_correct_movie_folder(
        self, mock_loguru_debug, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/root/Movie")
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(
            radarr_cli, "request_get", return_value=dict(folder="Movie")
        )
        request_put = mocker.patch.object(radarr_cli, "request_put")
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieFolderRename(radarr_cli).process([movie])

        request_put.assert_not_called()
        send_command.assert_not_called()
        assert (
            call("Processing pending movie folder renames")
            not in mock_loguru_debug.mock_calls
        )

    def test_process_batches_movie_folder_renames_by_root(
        self, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A", path="/rootA/OldA")
        movie_b = RadarrMovieItem(id=2, title="Movie B", path="/rootB/OldB")
        movie_c = RadarrMovieItem(id=3, title="Movie C", path="/rootA/OldC")
        mocker.patch.object(
            radarr_cli,
            "get_root_folder",
            return_value=[dict(path="/rootA"), dict(path="/rootB")],
        )
        mocker.patch.object(radarr_cli, "request_get").side_effect = [
            dict(folder="NewA"),
            dict(folder="NewB"),
            dict(folder="NewC"),
        ]
        request_put = mocker.patch.object(radarr_cli, "request_put")
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")
        send_command.side_effect = [dict(id=10), dict(id=20)]
        get_command = mocker.patch.object(
            radarr_cli,
            "get_command",
            side_effect=[
                dict(status="completed", result="successful"),
                dict(status="completed", result="successful"),
            ],
        )
        mocker.patch("renamarr.radarr.services.movie_folder_rename.sleep")

        MovieFolderRename(radarr_cli).process([movie_a, movie_b, movie_c])

        mock_loguru_debug.assert_any_call("Processing pending movie folder renames")
        request_put.assert_has_calls(
            [
                call(
                    path="/api/v3/movie/editor",
                    json_data=dict(
                        rootFolderPath="/rootA",
                        movieIds=[1, 3],
                        moveFiles=True,
                    ),
                ),
                call(
                    path="/api/v3/movie/editor",
                    json_data=dict(
                        rootFolderPath="/rootB",
                        movieIds=[2],
                        moveFiles=True,
                    ),
                ),
            ]
        )
        get_command.assert_has_calls([call(cid=10), call(cid=20)])
        send_command.assert_has_calls(
            [
                call(dict(priority="high", name="RefreshMovie", movieIds=[1, 3])),
                call(dict(priority="high", name="RefreshMovie", movieIds=[2])),
            ]
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Renaming Movie folder for movies: Movie A, Movie C"),
                call("Movie folder rename successful for movies: Movie A, Movie C"),
                call("Initiated disk scan of updated movies"),
                call("disk scan finished successfully"),
                call("Renaming Movie folder for movies: Movie B"),
                call("Movie folder rename successful for movies: Movie B"),
                call("Initiated disk scan of updated movies"),
                call("disk scan finished successfully"),
            ]
        )

    def test_process_logs_when_updated_movie_rescan_fails(
        self, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/root/Old")
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(radarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(radarr_cli, "request_put")
        mocker.patch.object(radarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            radarr_cli,
            "get_command",
            return_value=dict(status="completed", result="failed"),
        )
        mocker.patch("renamarr.radarr.services.movie_folder_rename.sleep")

        MovieFolderRename(radarr_cli).process([movie])

        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of updated movies"),
                call("disk scan failed"),
            ]
        )

    def test_process_raises_without_success_log_when_folder_rename_fails(
        self, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/root/Old")
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(radarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            radarr_cli,
            "request_put",
            side_effect=RuntimeError("Radarr rejected folder rename"),
        )
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        with pytest.raises(RuntimeError, match="Radarr rejected folder rename"):
            MovieFolderRename(radarr_cli).process([movie])

        send_command.assert_not_called()
        mock_loguru_info.assert_any_call("Renaming Movie folder for movies: Movie")
        assert (
            call("Movie folder rename successful for movies: Movie")
            not in mock_loguru_info.mock_calls
        )

    def test_process_warns_and_skips_movie_without_matching_root_folder(
        self, mock_loguru_warning, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/unmatched/Movie")
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        request_get = mocker.patch.object(radarr_cli, "request_get")
        request_put = mocker.patch.object(radarr_cli, "request_put")
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieFolderRename(radarr_cli).process([movie])

        mock_loguru_warning.assert_called_once_with(
            "Unable to determine matching Radarr root folder for movie path /unmatched/Movie"
        )
        request_get.assert_not_called()
        request_put.assert_not_called()
        send_command.assert_not_called()
