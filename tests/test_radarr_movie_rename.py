from unittest.mock import call

import pytest
from pycliarr.api import RadarrCli, RadarrMovieItem

from renamarr.radarr.services.movie_rename import MovieRename


class TestMovieRename:
    def test_process_skips_command_when_no_movies_need_rename(
        self, fake_observability, mock_loguru_debug, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A")
        movie_b = RadarrMovieItem(id=2, title="Movie B")
        mocker.patch(
            "renamarr.radarr.services.movie_rename.get_observability",
            return_value=fake_observability,
        )
        request_get = mocker.patch.object(radarr_cli, "request_get", return_value=[])
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieRename(radarr_cli).process([movie_a, movie_b])

        request_get.assert_has_calls(
            [
                call(path="/api/v3/rename", url_params=dict(movieId=1)),
                call(path="/api/v3/rename", url_params=dict(movieId=2)),
            ]
        )
        assert mock_loguru_debug.call_args_list == [
            call("Nothing to rename"),
            call("Nothing to rename"),
        ]
        send_command.assert_not_called()
        fake_observability.record_operation_scanned_items.assert_called_once_with(
            "radarr",
            "",
            "rename",
            2,
        )
        fake_observability.record_operation_candidate_items.assert_called_once_with(
            "radarr",
            "",
            "rename",
            0,
        )
        fake_observability.record_operation_run.assert_called_once_with(
            "radarr",
            "",
            "rename",
            "noop",
        )

    def test_process_sends_one_rename_movie_command_with_movie_ids(
        self, fake_observability, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A")
        movie_b = RadarrMovieItem(id=2, title="Movie B")
        mocker.patch(
            "renamarr.radarr.services.movie_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(radarr_cli, "request_get").side_effect = [
            [dict(movieId=1, movieFileId=10), dict(movieId=1, movieFileId=11)],
            [dict(movieId=2, movieFileId=20)],
        ]
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieRename(radarr_cli, name="movies").process([movie_a, movie_b])

        send_command.assert_called_once_with(
            {
                "name": "RenameMovie",
                "movieIds": [1, 2],
            }
        )
        mock_loguru_info.assert_has_calls(
            [
                call("Renaming Movies: Movie A, Movie B"),
                call("Movie rename successful for movies: Movie A, Movie B"),
            ]
        )
        fake_observability.start_span.assert_called_once_with(
            "renamarr.radarr.rename",
            attributes={
                "service": "radarr",
                "name": "movies",
                "operation": "rename",
            },
        )
        fake_observability.record_operation_scanned_items.assert_called_once_with(
            "radarr",
            "movies",
            "rename",
            2,
        )
        fake_observability.record_operation_candidate_items.assert_called_once_with(
            "radarr",
            "movies",
            "rename",
            2,
        )
        fake_observability.record_operation_items.assert_called_once_with(
            "radarr",
            "movies",
            "rename",
            "accepted",
            2,
        )
        fake_observability.record_operation_run.assert_called_once_with(
            "radarr",
            "movies",
            "rename",
            "accepted",
        )

    def test_process_records_failed_metric_when_rename_command_fails(
        self, fake_observability, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie = RadarrMovieItem(id=1, title="Movie")
        mocker.patch(
            "renamarr.radarr.services.movie_rename.get_observability",
            return_value=fake_observability,
        )
        mocker.patch.object(
            radarr_cli,
            "request_get",
            return_value=[dict(movieId=1, movieFileId=10)],
        )
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")
        exception = RuntimeError("BOOM!")
        send_command.side_effect = exception

        with pytest.raises(RuntimeError) as excinfo:
            MovieRename(radarr_cli, name="movies").process([movie])

        assert excinfo.value is exception
        fake_observability.record_operation_run.assert_called_once_with(
            "radarr",
            "movies",
            "rename",
            "failed",
        )
        fake_observability.record_operation_items.assert_called_once_with(
            "radarr",
            "movies",
            "rename",
            "failed",
            1,
        )
