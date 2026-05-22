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
        request = mocker.patch.object(radarr_cli._session, "request")
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieFolderRename(radarr_cli).process([movie])

        request.assert_not_called()
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
        request = mocker.patch.object(
            radarr_cli._session,
            "request",
            side_effect=[mocker.Mock(status_code=200), mocker.Mock(status_code=299)],
        )
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
        request.assert_has_calls(
            [
                call(
                    "PUT",
                    "test.tld/api/v3/movie/editor",
                    json=dict(
                        rootFolderPath="/rootA",
                        movieIds=[1, 3],
                        moveFiles=True,
                    ),
                ),
                call(
                    "PUT",
                    "test.tld/api/v3/movie/editor",
                    json=dict(
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
                call("Renaming Movie folders for movies: Movie A, Movie C"),
                call("Movie folder rename successful for movies: Movie A, Movie C"),
                call("Initiated disk scan of updated movies"),
                call("disk scan finished successfully"),
                call("Renaming Movie folder for movie: Movie B"),
                call("Movie folder rename successful for movies: Movie B"),
                call("Initiated disk scan of updated movies"),
                call("disk scan finished successfully"),
            ]
        )

    @pytest.mark.parametrize(
        ("movie_a_root", "movie_b_root"),
        [
            ("/movies", "/movies-4k"),
            ("/movies-4k", "/movies"),
        ],
    )
    def test_process_matches_movies_to_overlapping_root_folder_names(
        self, movie_a_root, movie_b_root, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A", path=f"{movie_a_root}/OldA")
        movie_b = RadarrMovieItem(id=2, title="Movie B", path=f"{movie_b_root}/OldB")
        mocker.patch.object(
            radarr_cli,
            "get_root_folder",
            return_value=[dict(path="/movies"), dict(path="/movies-4k")],
        )
        mocker.patch.object(radarr_cli, "request_get").side_effect = [
            dict(folder="NewA"),
            dict(folder="NewB"),
        ]
        request = mocker.patch.object(
            radarr_cli._session,
            "request",
            side_effect=[mocker.Mock(status_code=200), mocker.Mock(status_code=200)],
        )
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")
        send_command.side_effect = [dict(id=10), dict(id=20)]
        mocker.patch.object(
            radarr_cli,
            "get_command",
            side_effect=[
                dict(status="completed", result="successful"),
                dict(status="completed", result="successful"),
            ],
        )
        mocker.patch("renamarr.radarr.services.movie_folder_rename.sleep")

        MovieFolderRename(radarr_cli).process([movie_a, movie_b])

        request.assert_has_calls(
            [
                call(
                    "PUT",
                    "test.tld/api/v3/movie/editor",
                    json=dict(
                        rootFolderPath=movie_a_root,
                        movieIds=[1],
                        moveFiles=True,
                    ),
                ),
                call(
                    "PUT",
                    "test.tld/api/v3/movie/editor",
                    json=dict(
                        rootFolderPath=movie_b_root,
                        movieIds=[2],
                        moveFiles=True,
                    ),
                ),
            ]
        )
        send_command.assert_has_calls(
            [
                call(dict(priority="high", name="RefreshMovie", movieIds=[1])),
                call(dict(priority="high", name="RefreshMovie", movieIds=[2])),
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
        mocker.patch.object(
            radarr_cli._session, "request", return_value=mocker.Mock(status_code=200)
        )
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

    def test_process_skips_rescan_when_folder_rename_status_is_unsuccessful(
        self, mock_loguru_error, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/root/Old")
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(radarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            radarr_cli._session, "request", return_value=mocker.Mock(status_code=300)
        )
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieFolderRename(radarr_cli).process([movie])

        send_command.assert_not_called()
        mock_loguru_info.assert_any_call("Renaming Movie folder for movie: Movie")
        mock_loguru_error.assert_called_once_with(
            "Movie folder rename failed for movies: Movie: status code 300"
        )
        assert (
            call("Movie folder rename successful for movies: Movie")
            not in mock_loguru_info.mock_calls
        )
        assert (
            call("Initiated disk scan of updated movies")
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
        request = mocker.patch.object(radarr_cli._session, "request")
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieFolderRename(radarr_cli).process([movie])

        mock_loguru_warning.assert_called_once_with(
            "Unable to determine matching Radarr root folder for movie path /unmatched/Movie"
        )
        request_get.assert_not_called()
        request.assert_not_called()
        send_command.assert_not_called()
