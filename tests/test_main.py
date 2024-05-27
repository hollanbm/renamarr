import pytest
from config_schema import CONFIG_SCHEMA
from main import Main
from pycliarr.api import CliArrError
from pyconfigparser import Config, ConfigError, ConfigFileNotFoundError, configparser
from schedule import Job
from sonarr_renamarr import SonarrRenamarr
from sonarr_series_scanner import SonarrSeriesScanner

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

        series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")
        renamarr = mocker.patch.object(SonarrRenamarr, "scan")

        Main().start()

        assert not series_scanner.called
        assert not renamarr.called

    def test_series_scanner_scan(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")

        Main().start()
        assert series_scanner.called

    def test_series_scanner_hourly_job(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")

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

        series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")
        series_scanner.side_effect = exception

        Main().start()

        mock_loguru_error.assert_called_once_with(exception)

    def test_renamarr_scan(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        renamarr = mocker.patch.object(SonarrRenamarr, "scan")

        Main().start()
        assert renamarr.called

    def test_renamarr_hourly_job(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        renamarr = mocker.patch.object(SonarrRenamarr, "scan")

        Main().start()
        assert renamarr.called
        assert job.called

    def test_renamarr_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        renamarr = mocker.patch.object(SonarrRenamarr, "scan")
        renamarr.side_effect = exception

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
