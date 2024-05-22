import pytest
from config_schema import CONFIG_SCHEMA
from existing_renamer import ExistingRenamer
from main import Main
from pycliarr.api import CliArrError
from pyconfigparser import Config, ConfigError, ConfigFileNotFoundError, configparser
from schedule import Job
from series_scanner import SeriesScanner

# disable config caching
configparser.hold_an_instance = False


class TestMain:
    @pytest.fixture
    def config(self) -> Config:
        return configparser.get_config(
            CONFIG_SCHEMA,
            config_dir="tests/fixtures",
            file_name="single_sonarr.yml",
        )

    def test_all_disabled(self, config, mocker) -> None:
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config

        series_scanner = mocker.patch.object(SeriesScanner, "scan")
        existing_renamer = mocker.patch.object(ExistingRenamer, "scan")

        Main().start()

        assert not series_scanner.called
        assert not existing_renamer.called

    def test_series_scanner_scan(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        series_scanner = mocker.patch.object(SeriesScanner, "scan")

        Main().start()
        assert series_scanner.called

    def test_series_scanner_hourly_job(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        series_scanner = mocker.patch.object(SeriesScanner, "scan")

        Main().start()
        assert series_scanner.called
        assert job.called

    def test_series_scanner_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        series_scanner = mocker.patch.object(SeriesScanner, "scan")
        series_scanner.side_effect = exception

        Main().start()

        mock_loguru_error.assert_called_once_with(exception)

    def test_existing_renamer_scan(self, config, mocker) -> None:
        config.sonarr[0].existing_renamer.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        existing_renamer = mocker.patch.object(ExistingRenamer, "scan")

        Main().start()
        assert existing_renamer.called

    def test_existing_renamer_hourly_job(self, config, mocker) -> None:
        config.sonarr[0].existing_renamer.enabled = True
        config.sonarr[0].existing_renamer.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        existing_renamer = mocker.patch.object(ExistingRenamer, "scan")

        Main().start()
        assert existing_renamer.called
        assert job.called

    def test_existing_renamer_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].existing_renamer.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        existing_renamer = mocker.patch.object(ExistingRenamer, "scan")
        existing_renamer.side_effect = exception

        Main().start()

        mock_loguru_error.assert_called_once_with(exception)

    def test_config_parser_error(self, mock_loguru_error, capsys, mocker) -> None:
        exception = ConfigError("BOOM!")
        mocker.patch("pyconfigparser.configparser.get_config").side_effect = exception

        with pytest.raises(SystemExit) as excinfo:
            Main().start()

        mock_loguru_error.assert_called_once_with(exception)
        assert excinfo.value.code == 1

    def test_config_file_not_found_error(
        self, mock_loguru_error, capsys, mocker
    ) -> None:
        exception = ConfigFileNotFoundError("BOOM!")
        mocker.patch("pyconfigparser.configparser.get_config").side_effect = exception

        with pytest.raises(SystemExit) as excinfo:
            Main().start()

        mock_loguru_error.assert_called_once_with(exception)
        assert excinfo.value.code == 1
