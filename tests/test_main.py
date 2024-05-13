import pytest
from config_schema import CONFIG_SCHEMA
from existing_renamer import ExistingRenamer
from main import Main
from pyconfigparser import Config, configparser
from series_scanner import SeriesScanner

# disable config caching
configparser.hold_an_instance = False


class TestMain:
    def get_single_config(self) -> Config:
        return configparser.get_config(
            CONFIG_SCHEMA,
            config_dir="tests/fixtures",
            file_name="single_sonarr.yml",
        )

    @pytest.fixture
    def all_disabled(self, mocker):
        mocker.patch(
            "pyconfigparser.configparser.get_config"
        ).return_value = self.get_single_config()

    @pytest.fixture
    def series_scanner_enabled(self, mocker):
        config = self.get_single_config()
        config.sonarr[0].series_scanner.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config

    @pytest.fixture
    def existing_renamer_enabled(self, mocker):
        config = self.get_single_config()
        config.sonarr[0].existing_renamer.enabled = True
        mocker.patch("pyconfigparser.configparser.get_config").return_value = config

    def test_all_disabled(self, all_disabled, mocker):
        series_scanner = mocker.patch.object(SeriesScanner, "scan")
        existing_renamer = mocker.patch.object(ExistingRenamer, "scan")

        assert not series_scanner.called
        assert not existing_renamer.called

    def test_series_scanner_scan(self, series_scanner_enabled, mocker) -> None:
        series_scanner = mocker.patch.object(SeriesScanner, "scan")

        Main().start()
        assert series_scanner.called

    def test_existing_renamer_scan(self, existing_renamer_enabled, mocker) -> None:
        existing_renamer = mocker.patch.object(ExistingRenamer, "scan")

        Main().start()
        assert existing_renamer.called
