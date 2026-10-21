"""Configuration regressions for baseline 57cfcdc6867f."""

import os
import tempfile
from unittest import mock

from unittest.mock import patch

import portal_config
import pytest


@pytest.mark.parametrize(
    "failure", [PermissionError("private diagnostics"), OSError("read failed")]
)
def test_unreadable_config_preserves_path_and_error_cause(failure):
    with (
        patch.object(portal_config, "CONF_FILE", "/restricted/kiosk.conf"),
        patch.object(os.path, "isfile", return_value=True),
        patch("builtins.open", side_effect=failure),
        pytest.raises(
            portal_config.ConfigReadError, match="/restricted/kiosk.conf"
        ) as error,
    ):
        portal_config.load_config()
    assert error.value.__cause__ is failure


def test_missing_config_has_unique_hotspot_credentials():
    with patch.object(portal_config, "CONF_FILE", "/nonexistent/wrzdj-kiosk.conf"):
        first = portal_config.load_config()
        second = portal_config.load_config()
    assert first["HOTSPOT_PASSWORD"] != second["HOTSPOT_PASSWORD"]
    assert 8 <= len(first["HOTSPOT_PASSWORD"]) <= 63


def test_empty_config_password_gets_generated(tmp_path):
    config_file = tmp_path / "kiosk.conf"
    config_file.write_text("HOTSPOT_PASSWORD=\n")
    with patch.object(portal_config, "CONF_FILE", str(config_file)):
        config = portal_config.load_config()
    assert len(config["HOTSPOT_PASSWORD"]) >= 8


def test_installer_settings_do_not_leak_into_portal_config(tmp_path):
    config_file = tmp_path / "kiosk.conf"
    config_file.write_text("KIOSK_ROTATION=left\nEXTRA_CHROMIUM_FLAGS=--kiosk\n")
    with patch.object(portal_config, "CONF_FILE", str(config_file)):
        config = portal_config.load_config()
    assert set(config) == {"KIOSK_URL", "HOTSPOT_SSID", "HOTSPOT_PASSWORD"}


class TestLoadConfig:
    def test_defaults_when_file_missing(self):
        with mock.patch.object(os.path, "isfile", return_value=False):
            config = portal_config.load_config()
        assert config["KIOSK_URL"] == portal_config.DEFAULT_KIOSK_URL
        assert config["HOTSPOT_SSID"] == portal_config.DEFAULT_HOTSPOT_SSID
        assert 8 <= len(config["HOTSPOT_PASSWORD"]) <= 63

    def test_reads_valid_config(self):
        content = (
            "KIOSK_URL=https://example.com/kiosk\n"
            "HOTSPOT_SSID=MyKiosk\n"
            "HOTSPOT_PASSWORD=secret123\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal_config, "CONF_FILE", f.name):
                    config = portal_config.load_config()
                assert config["KIOSK_URL"] == "https://example.com/kiosk"
                assert config["HOTSPOT_SSID"] == "MyKiosk"
                assert config["HOTSPOT_PASSWORD"] == "secret123"
            finally:
                os.unlink(f.name)

    def test_ignores_comments_and_blank_lines(self):
        content = "# This is a comment\n\nHOTSPOT_SSID=TestSSID\n  # Another comment\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal_config, "CONF_FILE", f.name):
                    config = portal_config.load_config()
                assert config["HOTSPOT_SSID"] == "TestSSID"
            finally:
                os.unlink(f.name)

    def test_strips_quotes(self):
        content = 'HOTSPOT_SSID="Quoted SSID"\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal_config, "CONF_FILE", f.name):
                    config = portal_config.load_config()
                assert config["HOTSPOT_SSID"] == "Quoted SSID"
            finally:
                os.unlink(f.name)

    def test_ignores_unknown_keys(self):
        content = "UNKNOWN_KEY=something\nHOTSPOT_SSID=Valid\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal_config, "CONF_FILE", f.name):
                    config = portal_config.load_config()
                assert "UNKNOWN_KEY" not in config
                assert config["HOTSPOT_SSID"] == "Valid"
            finally:
                os.unlink(f.name)

    def test_skips_lines_without_equals(self):
        content = "no-equals-here\nHOTSPOT_SSID=GoodLine\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal_config, "CONF_FILE", f.name):
                    config = portal_config.load_config()
                assert config["HOTSPOT_SSID"] == "GoodLine"
            finally:
                os.unlink(f.name)

    def test_handles_value_with_equals(self):
        content = "KIOSK_URL=https://example.com?foo=bar\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal_config, "CONF_FILE", f.name):
                    config = portal_config.load_config()
                assert config["KIOSK_URL"] == "https://example.com?foo=bar"
            finally:
                os.unlink(f.name)
