from unittest.mock import call

from pycliarr.api import RadarrCli, RadarrMovieItem

from renamarr.radarr.services.movie_rename import MovieRename


class TestMovieRename:
    def test_process_skips_command_when_no_movies_need_rename(
        self, mock_loguru_debug, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A")
        movie_b = RadarrMovieItem(id=2, title="Movie B")
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

    def test_process_sends_one_rename_movie_command_with_movie_ids(
        self, mock_loguru_info, mocker
    ) -> None:
        radarr_cli = RadarrCli("test.tld", "test-api-key")
        movie_a = RadarrMovieItem(id=1, title="Movie A")
        movie_b = RadarrMovieItem(id=2, title="Movie B")
        mocker.patch.object(radarr_cli, "request_get").side_effect = [
            [dict(movieId=1, movieFileId=10), dict(movieId=1, movieFileId=11)],
            [dict(movieId=2, movieFileId=20)],
        ]
        send_command = mocker.patch.object(radarr_cli, "_sendCommand")

        MovieRename(radarr_cli).process([movie_a, movie_b])

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
