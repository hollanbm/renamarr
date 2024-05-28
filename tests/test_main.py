from unittest.mock import call

import pytest
from config_schema import CONFIG_SCHEMA
from main import Main
from pycliarr.api import CliArrError
from pyconfigparser import Config, ConfigError, ConfigFileNotFoundError, configparser
from radarr_renamarr import RadarrRenamarr
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
            file_name="disabled.yml",
        )

    @pytest.fixture
    def legacy_sonarr_config(self) -> Config:
        return configparser.get_config(
            CONFIG_SCHEMA,
            config_dir="tests/fixtures",
            file_name="legacy_sonarr.yml",
        )

    def test_all_disabled(self, config, mocker) -> None:
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config

        series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")
        sonarr_renamarr = mocker.patch.object(SonarrRenamarr, "scan")
        radarr_renamarr = mocker.patch.object(RadarrRenamarr, "scan")
        job = mocker.patch.object(Job, "do")

        Main().start()

        series_scanner.assert_not_called()
        sonarr_renamarr.assert_not_called()
        radarr_renamarr.assert_not_called()
        job.assert_not_called()

    def test_sonarr_series_scanner_scan(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        sonarr_series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")

        Main().start()

        sonarr_series_scanner.assert_called()

    def test_sonarr_series_scanner_hourly_job(self, config, mocker) -> None:
        config.sonarr[0].series_scanner.enabled = True
        config.sonarr[0].series_scanner.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        sonarr_series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")

        Main().start()

        sonarr_series_scanner.assert_called()
        job.assert_called()

    def test_sonarr_series_scanner_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        sonarr_series_scanner = mocker.patch.object(SonarrSeriesScanner, "scan")
        sonarr_series_scanner.side_effect = exception

        Main().start()

        mock_loguru_error.assert_called_once_with(exception)

    def test_sonarr_renamarr_scan(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        sonarr_renamarr = mocker.patch.object(SonarrRenamarr, "scan")

        Main().start()
        sonarr_renamarr.assert_called()

    def test_sonarr_renamarr_hourly_job(self, config, mocker) -> None:
        config.sonarr[0].renamarr.enabled = True
        config.sonarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        renamarr = mocker.patch.object(SonarrRenamarr, "scan")

        Main().start()

        renamarr.assert_called()
        job.assert_called()

    def test_sonarr_renamarr_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.sonarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        sonarr_renamarr = mocker.patch.object(SonarrRenamarr, "scan")
        sonarr_renamarr.side_effect = exception

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

    def test_legacy_config_existing_renamer_enabled(
        self, mocker, legacy_sonarr_config, mock_loguru_warning
    ):
        legacy_sonarr_config.sonarr[0].existing_renamer.enabled = True

        mocker.patch(
            "pyconfigparser.configparser.get_config"
        ).return_value = legacy_sonarr_config

        mocker.patch.object(Job, "do")

        sonarr_renamarr = mocker.patch.object(SonarrRenamarr, "scan")

        Main().start()

        sonarr_renamarr.assert_called()
        mock_loguru_warning.assert_has_calls(
            [
                call(
                    "sonarr[].existing_renamer config option, has been renamed to sonarr[].renamarr. Please update config, as this will stop working in future versions"
                ),
                call(
                    "Please see example config for comparison -- https://github.com/hollanbm/sonarr-series-scanner/blob/main/docker/config.yml.example"
                ),
            ]
        )

    def test_legacy_config_existing_renamer_exception(
        self, mocker, legacy_sonarr_config, mock_loguru_error
    ):
        legacy_sonarr_config.sonarr[0].existing_renamer.enabled = True

        mocker.patch(
            "pyconfigparser.configparser.get_config"
        ).return_value = legacy_sonarr_config

        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        sonarr_renamarr = mocker.patch.object(SonarrRenamarr, "scan")
        sonarr_renamarr.side_effect = exception

        Main().start()

        mock_loguru_error.assert_called_once_with(exception)

    def test_radarr_renamarr_scan(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True

        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        radarr_renamarr = mocker.patch.object(RadarrRenamarr, "scan")

        Main().start()

        radarr_renamarr.assert_called()

    def test_radarr_renamarr_hourly_job(self, config, mocker) -> None:
        config.radarr[0].renamarr.enabled = True
        config.radarr[0].renamarr.hourly_job = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        job = mocker.patch.object(Job, "do")

        radarr_renamarr = mocker.patch.object(RadarrRenamarr, "scan")

        Main().start()

        radarr_renamarr.assert_called
        job.assert_called

    def test_radarr_renamarr_pycliarr_exception(
        self, config, mock_loguru_error, mocker
    ) -> None:
        config.radarr[0].renamarr.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config
        mocker.patch.object(Job, "do")

        exception = CliArrError("BOOM!")

        renamarr = mocker.patch.object(RadarrRenamarr, "scan")
        renamarr.side_effect = exception

        Main().start()

        mock_loguru_error.assert_called_once_with(exception)
