from pathlib import PurePosixPath
from unittest.mock import ANY, call

import pytest
from pycliarr.api import RadarrCli, RadarrMovieItem

from renamarr.radarr.services.movie_folder_rename import (
    MAX_WAIT_SECONDS,
    MovieFolderRename,
    MovieRootFolderNotFoundError,
)


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
        self, fake_observability, mock_loguru_info, mock_loguru_debug, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A", path="/rootA/OldA")
        movie_b = RadarrMovieItem(id=2, title="Movie B", path="/rootB/OldB")
        movie_c = RadarrMovieItem(id=3, title="Movie C", path="/rootA/OldC")
        mocker.patch(
            "renamarr.radarr.services.movie_folder_rename.get_observability",
            return_value=fake_observability,
        )
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

        MovieFolderRename(radarr_cli, name="movies").process(
            [movie_a, movie_b, movie_c]
        )

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
        fake_observability.start_span.assert_called_once_with(
            "renamarr.radarr.folder_rename",
            attributes={
                "service": "radarr",
                "name": "movies",
                "operation": "folder_rename",
            },
        )
        fake_observability.record_operation_items.assert_has_calls(
            [
                call("radarr", "movies", "folder_rename", "accepted", 2),
                call("radarr", "movies", "folder_rename", "accepted", 1),
            ]
        )
        fake_observability.record_operation_scanned_items.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            3,
        )
        fake_observability.record_operation_candidate_items.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            3,
        )
        fake_observability.record_operation_run.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            "accepted",
        )
        assert fake_observability.record_arr_command.call_args_list == [
            call("radarr", "movies", "RefreshMovie", "successful", ANY),
            call("radarr", "movies", "RefreshMovie", "successful", ANY),
        ]

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

    def test_process_sorts_root_folders_before_matching_movies(self, mocker) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/rootA/Movie")
        mocker.patch.object(
            radarr_cli,
            "get_root_folder",
            return_value=[dict(path="/rootB"), dict(path="/rootA")],
        )
        mocker.patch.object(
            radarr_cli, "request_get", return_value=dict(folder="Movie")
        )
        service = MovieFolderRename(radarr_cli)
        find_movie_root_folder = mocker.spy(
            service, "_MovieFolderRename__find_movie_root_folder"
        )

        service.process([movie])

        assert find_movie_root_folder.call_args.args[1] == [
            dict(path="/rootA"),
            dict(path="/rootB"),
        ]

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

    def test_process_logs_when_updated_movie_rescan_times_out(
        self, mock_loguru_error, mock_loguru_info, mocker
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
        get_command = mocker.patch.object(
            radarr_cli,
            "get_command",
            return_value=dict(status="started"),
        )
        sleep = mocker.patch("renamarr.radarr.services.movie_folder_rename.sleep")
        mocker.patch(
            "renamarr.radarr.services.movie_folder_rename.time.time",
            side_effect=[0, 0, MAX_WAIT_SECONDS, MAX_WAIT_SECONDS],
        )

        MovieFolderRename(radarr_cli).process([movie])

        get_command.assert_called_once_with(cid=10)
        sleep.assert_called_once_with(10)
        mock_loguru_error.assert_called_once_with(
            "Timed out waiting for Radarr movie rescan command 10 after 300 seconds"
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Initiated disk scan of updated movies"),
                call("disk scan failed"),
            ]
        )

    def test_process_skips_rescan_when_folder_rename_status_is_unsuccessful(
        self, fake_observability, mock_loguru_error, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/root/Old")
        mocker.patch(
            "renamarr.radarr.services.movie_folder_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(radarr_cli, "request_get", return_value=dict(folder="New"))
        mocker.patch.object(
            radarr_cli._session, "request", return_value=mocker.Mock(status_code=300)
        )
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieFolderRename(radarr_cli, name="movies").process([movie])

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
        fake_observability.record_operation_items.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            "failed",
            1,
        )
        fake_observability.record_operation_run.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            "failed",
        )

    def test_process_records_failed_metric_when_folder_rename_request_fails(
        self, fake_observability, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path="/root/Old")
        mocker.patch(
            "renamarr.radarr.services.movie_folder_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        mocker.patch.object(radarr_cli, "request_get", return_value=dict(folder="New"))
        exception = RuntimeError("BOOM!")
        mocker.patch.object(radarr_cli._session, "request", side_effect=exception)

        with pytest.raises(RuntimeError) as excinfo:
            MovieFolderRename(radarr_cli, name="movies").process([movie])

        assert excinfo.value is exception
        fake_observability.record_operation_run.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            "failed",
        )
        fake_observability.record_operation_items.assert_called_once_with(
            "radarr",
            "movies",
            "folder_rename",
            "failed",
            1,
        )

    def test_process_logs_error_and_continues_after_movie_without_matching_root_folder(
        self, mock_loguru_error, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        unmatched_movie = RadarrMovieItem(
            id=1, title="Unmatched Movie", path="/unmatched/Movie"
        )
        matched_movie = RadarrMovieItem(id=2, title="Matched Movie", path="/root/Old")
        mocker.patch.object(
            radarr_cli, "get_root_folder", return_value=[dict(path="/root")]
        )
        request_get = mocker.patch.object(
            radarr_cli, "request_get", return_value=dict(folder="New")
        )
        request = mocker.patch.object(
            radarr_cli._session, "request", return_value=mocker.Mock(status_code=200)
        )
        send_command = mocker.patch.object(
            radarr_cli, "_sendCommand", return_value=dict(id=10)
        )
        mocker.patch.object(
            radarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.radarr.services.movie_folder_rename.sleep")

        MovieFolderRename(radarr_cli).process([unmatched_movie, matched_movie])

        mock_loguru_error.assert_called_once_with(
            "Unable to determine matching Radarr root folder for movie path /unmatched/Movie"
        )
        request_get.assert_called_once_with(path="/api/v3/movie/2/folder")
        request.assert_called_once_with(
            "PUT",
            "test.tld/api/v3/movie/editor",
            json=dict(rootFolderPath="/root", movieIds=[2], moveFiles=True),
        )
        send_command.assert_called_once_with(
            dict(priority="high", name="RefreshMovie", movieIds=[2])
        )

    def test_find_movie_root_folder_raises_when_no_root_folder_matches(self) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        service = MovieFolderRename(radarr_cli)

        with pytest.raises(
            MovieRootFolderNotFoundError,
            match=(
                "Unable to determine matching Radarr root folder for movie path "
                "/unmatched/Movie"
            ),
        ):
            service._MovieFolderRename__find_movie_root_folder(
                PurePosixPath("/unmatched/Movie"),
                [dict(path="/root")],
            )

    @pytest.mark.parametrize(
        ("movie_path", "root_folders", "expected_root_folder"),
        [
            (
                "/data/media/movies/OldName",
                [dict(path="/data/media"), dict(path="/data/media/movies")],
                "/data/media/movies",
            ),
            (
                "/data/media/movies",
                [dict(path="/data/media"), dict(path="/data/media/movies")],
                "/data/media/movies",
            ),
        ],
        ids=["nested-roots", "root-equals-movie-path"],
    )
    def test_process_uses_deepest_matching_root_folder(
        self,
        movie_path,
        root_folders,
        expected_root_folder,
        mocker,
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie", path=movie_path)
        mocker.patch.object(
            radarr_cli,
            "get_root_folder",
            return_value=root_folders,
        )
        mocker.patch.object(radarr_cli, "request_get", return_value=dict(folder="New"))
        request = mocker.patch.object(
            radarr_cli._session, "request", return_value=mocker.Mock(status_code=200)
        )
        mocker.patch.object(radarr_cli, "_sendCommand", return_value=dict(id=10))
        mocker.patch.object(
            radarr_cli,
            "get_command",
            return_value=dict(status="completed", result="successful"),
        )
        mocker.patch("renamarr.radarr.services.movie_folder_rename.sleep")

        MovieFolderRename(radarr_cli).process([movie])

        request.assert_called_once_with(
            "PUT",
            "test.tld/api/v3/movie/editor",
            json=dict(
                rootFolderPath=expected_root_folder,
                movieIds=[1],
                moveFiles=True,
            ),
        )
