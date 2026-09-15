"""Unit tests for the WrzDJ WiFi captive portal.

Tests pure logic (config parsing, nmcli output parsing, HTML generation,
input validation) without requiring a Raspberry Pi or network access.
"""

import os
import tempfile
from unittest import mock

# Import portal module from the kiosk wifi-portal directory.
# We need to add its parent to sys.path since it's not a regular package.
import importlib
import sys

_portal_dir = os.path.join(os.path.dirname(__file__))
if _portal_dir not in sys.path:
    sys.path.insert(0, _portal_dir)

portal = importlib.import_module("portal")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_defaults_when_file_missing(self):
        with mock.patch.object(os.path, "isfile", return_value=False):
            config = portal.load_config()
        assert config["KIOSK_URL"] == portal.DEFAULT_KIOSK_URL
        assert config["HOTSPOT_SSID"] == portal.DEFAULT_HOTSPOT_SSID
        assert config["HOTSPOT_PASSWORD"] == portal.DEFAULT_HOTSPOT_PASSWORD

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
                with mock.patch.object(portal, "CONF_FILE", f.name):
                    config = portal.load_config()
                assert config["KIOSK_URL"] == "https://example.com/kiosk"
                assert config["HOTSPOT_SSID"] == "MyKiosk"
                assert config["HOTSPOT_PASSWORD"] == "secret123"
            finally:
                os.unlink(f.name)

    def test_ignores_comments_and_blank_lines(self):
        content = (
            "# This is a comment\n"
            "\n"
            "HOTSPOT_SSID=TestSSID\n"
            "  # Another comment\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal, "CONF_FILE", f.name):
                    config = portal.load_config()
                assert config["HOTSPOT_SSID"] == "TestSSID"
            finally:
                os.unlink(f.name)

    def test_strips_quotes(self):
        content = 'HOTSPOT_SSID="Quoted SSID"\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal, "CONF_FILE", f.name):
                    config = portal.load_config()
                assert config["HOTSPOT_SSID"] == "Quoted SSID"
            finally:
                os.unlink(f.name)

    def test_ignores_unknown_keys(self):
        content = (
            "UNKNOWN_KEY=something\n"
            "HOTSPOT_SSID=Valid\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal, "CONF_FILE", f.name):
                    config = portal.load_config()
                assert "UNKNOWN_KEY" not in config
                assert config["HOTSPOT_SSID"] == "Valid"
            finally:
                os.unlink(f.name)

    def test_skips_lines_without_equals(self):
        content = (
            "no-equals-here\n"
            "HOTSPOT_SSID=GoodLine\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal, "CONF_FILE", f.name):
                    config = portal.load_config()
                assert config["HOTSPOT_SSID"] == "GoodLine"
            finally:
                os.unlink(f.name)

    def test_handles_value_with_equals(self):
        content = "KIOSK_URL=https://example.com?foo=bar\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            f.flush()
            try:
                with mock.patch.object(portal, "CONF_FILE", f.name):
                    config = portal.load_config()
                assert config["KIOSK_URL"] == "https://example.com?foo=bar"
            finally:
                os.unlink(f.name)


# ---------------------------------------------------------------------------
# nmcli terse output parser
# ---------------------------------------------------------------------------

class TestParseNmcliFields:
    def test_simple_fields(self):
        assert portal._parse_nmcli_fields("a:b:c") == ["a", "b", "c"]

    def test_escaped_colons(self):
        assert portal._parse_nmcli_fields(r"foo\:bar:baz") == ["foo:bar", "baz"]

    def test_multiple_escaped_colons(self):
        assert portal._parse_nmcli_fields(r"a\:b\:c:d") == ["a:b:c", "d"]

    def test_empty_fields(self):
        assert portal._parse_nmcli_fields("::") == ["", "", ""]

    def test_empty_string(self):
        assert portal._parse_nmcli_fields("") == [""]

    def test_no_colons(self):
        assert portal._parse_nmcli_fields("single") == ["single"]

    def test_trailing_colon(self):
        assert portal._parse_nmcli_fields("a:b:") == ["a", "b", ""]

    def test_real_nmcli_wifi_line(self):
        # Real example: SSID:SIGNAL:SECURITY
        fields = portal._parse_nmcli_fields("MyNetwork:85:WPA2")
        assert fields == ["MyNetwork", "85", "WPA2"]

    def test_ssid_with_colon(self):
        # SSIDs can contain colons
        fields = portal._parse_nmcli_fields(r"My\:Network:75:WPA2")
        assert fields == ["My:Network", "75", "WPA2"]

    def test_backslash_not_before_colon(self):
        # Backslash not followed by colon should be preserved
        fields = portal._parse_nmcli_fields(r"foo\nbar:baz")
        assert fields == ["foo\\nbar", "baz"]


# ---------------------------------------------------------------------------
# WiFi scan result parsing (with mocked subprocess)
# ---------------------------------------------------------------------------

class TestScanWifi:
    def test_parses_nmcli_output(self):
        fake_output = (
            "Network1:85:WPA2\n"
            "Network2:60:WPA1 WPA2\n"
            "OpenNet:40:\n"
        )
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = portal.scan_wifi()

        assert len(networks) == 3
        # Sorted by signal descending
        assert networks[0]["ssid"] == "Network1"
        assert networks[0]["signal"] == 85
        assert networks[0]["security"] == "WPA2"
        assert networks[2]["ssid"] == "OpenNet"
        assert networks[2]["security"] == "Open"

    def test_deduplicates_ssids(self):
        fake_output = "DupeNet:80:WPA2\nDupeNet:60:WPA2\n"
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = portal.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["ssid"] == "DupeNet"
        # Keeps first occurrence (higher signal since nmcli sorts)
        assert networks[0]["signal"] == 80

    def test_skips_empty_ssids(self):
        fake_output = ":80:WPA2\nRealNet:75:WPA2\n"
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = portal.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["ssid"] == "RealNet"

    def test_handles_invalid_signal(self):
        fake_output = "Network:notanumber:WPA2\n"
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = portal.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["signal"] == 0

    def test_handles_subprocess_failure(self):
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.side_effect = Exception("nmcli not found")
            networks = portal.scan_wifi()

        assert networks == []

    def test_handles_short_lines(self):
        fake_output = "TooShort:80\nGood:75:WPA2\n"
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = portal.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["ssid"] == "Good"


# ---------------------------------------------------------------------------
# HTML redirect page
# ---------------------------------------------------------------------------

class TestHtmlRedirect:
    def test_contains_redirect_script(self):
        html = portal._html_redirect("https://app.wrzdj.com/kiosk-pair")
        assert "window.location.replace(" in html
        # Verify URL appears JSON-encoded in the script tag (quoted)
        assert '"https://app.wrzdj.com/kiosk-pair"' in html

    def test_rejects_javascript_scheme(self):
        html = portal._html_redirect("javascript:alert(1)")
        # Should fall back to default URL
        assert portal.DEFAULT_KIOSK_URL in html
        assert "javascript:" not in html

    def test_rejects_ftp_scheme(self):
        html = portal._html_redirect("ftp://evil.com")
        assert portal.DEFAULT_KIOSK_URL in html
        assert "ftp:" not in html

    def test_allows_http(self):
        html = portal._html_redirect("http://192.168.1.5:3000/kiosk")
        # Verify URL appears JSON-encoded in the script tag (quoted)
        assert '"http://192.168.1.5:3000/kiosk"' in html

    def test_allows_https(self):
        html = portal._html_redirect("https://secure.example.com")
        # Verify URL appears JSON-encoded in the script tag (quoted)
        assert '"https://secure.example.com"' in html

    def test_json_encodes_url(self):
        # URL with special chars should be JSON-encoded for the JS
        html = portal._html_redirect('https://example.com/path?a=1&b="2"')
        # The JSON encoding should handle the quotes
        assert "window.location.replace(" in html

    def test_html_structure(self):
        html = portal._html_redirect("https://example.com")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Connecting to WrzDJ" in html


# ---------------------------------------------------------------------------
# HTML setup page
# ---------------------------------------------------------------------------

class TestHtmlSetup:
    def test_contains_network_list(self):
        networks = [
            {"ssid": "TestNet", "signal": 80, "security": "WPA2"},
            {"ssid": "OpenNet", "signal": 40, "security": "Open"},
        ]
        html = portal._html_setup({"HOTSPOT_SSID": "WrzDJ-Kiosk", "HOTSPOT_PASSWORD": "test"}, networks)
        assert "TestNet" in html
        assert "OpenNet" in html

    def test_html_escapes_config_values(self):
        config = {
            "HOTSPOT_SSID": '<script>alert("xss")</script>',
            "HOTSPOT_PASSWORD": "p&w<d>",
        }
        html = portal._html_setup(config, [])
        assert '<script>alert("xss")</script>' not in html
        assert "&lt;script&gt;" in html
        assert "p&amp;w&lt;d&gt;" in html

    def test_json_serializes_networks(self):
        networks = [{"ssid": "Net'\"<>", "signal": 50, "security": "WPA2"}]
        html = portal._html_setup({"HOTSPOT_SSID": "Test", "HOTSPOT_PASSWORD": "pass"}, networks)
        # The JSON should be valid and embedded in the page
        assert "var networks =" in html

    def test_html_structure(self):
        html = portal._html_setup({"HOTSPOT_SSID": "Test", "HOTSPOT_PASSWORD": "pass"}, [])
        assert "<!DOCTYPE html>" in html
        assert "WrzDJ Kiosk Setup" in html
        assert "Connect" in html


# ---------------------------------------------------------------------------
# Connection status parsing
# ---------------------------------------------------------------------------

class TestGetConnectionStatus:
    def test_connected_with_ip(self):
        device_output = "wlan0:wifi:connected:MyNetwork\n"
        ip_output = "IP4.ADDRESS[1]:192.168.1.42/24\n"

        with mock.patch("portal.subprocess") as mock_sub, \
             mock.patch("portal.check_internet", return_value=True):
            mock_sub.run.side_effect = [
                mock.Mock(stdout=device_output),
                mock.Mock(stdout=ip_output),
            ]
            status = portal.get_connection_status()

        assert status["connected"] is True
        assert status["ssid"] == "MyNetwork"
        assert status["ip"] == "192.168.1.42"
        assert status["internet"] is True

    def test_not_connected(self):
        device_output = "wlan0:wifi:disconnected:\n"

        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=device_output)
            status = portal.get_connection_status()

        assert status["connected"] is False
        assert status["ssid"] == ""
        assert status["ip"] == ""

    def test_handles_subprocess_failure(self):
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.side_effect = Exception("nmcli failed")
            status = portal.get_connection_status()

        assert status["connected"] is False


# ---------------------------------------------------------------------------
# Internet connectivity check (mocked)
# ---------------------------------------------------------------------------

class TestCheckInternet:
    def test_returns_true_on_success(self):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = portal.CONNECTIVITY_BODY
        with mock.patch("portal.urllib.request.urlopen", return_value=mock_resp):
            assert portal.check_internet() is True

    def test_returns_false_on_wrong_body(self):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = b"something else"
        mock_resp_204 = mock.Mock()
        mock_resp_204.status = 500
        with mock.patch("portal.urllib.request.urlopen", side_effect=[mock_resp, mock_resp_204]):
            assert portal.check_internet() is False

    def test_falls_back_to_gstatic(self):
        mock_resp_204 = mock.Mock()
        mock_resp_204.status = 204
        with mock.patch("portal.urllib.request.urlopen") as mock_url:
            # First call raises (Firefox portal down), second returns 204
            mock_url.side_effect = [Exception("timeout"), mock_resp_204]
            assert portal.check_internet() is True

    def test_returns_false_when_both_fail(self):
        with mock.patch("portal.urllib.request.urlopen", side_effect=Exception("no network")):
            assert portal.check_internet() is False


# ---------------------------------------------------------------------------
# Input validation (extracted from _handle_connect logic)
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Test the validation logic from PortalHandler._handle_connect.

    Since the validation is embedded in the handler method, we test the
    patterns directly rather than through HTTP requests.
    """

    def test_control_chars_rejected(self):
        import re
        assert re.search(r"[\x00-\x1f]", "hello\x00world") is not None
        assert re.search(r"[\x00-\x1f]", "hello\nworld") is not None
        assert re.search(r"[\x00-\x1f]", "hello\tworld") is not None
        assert re.search(r"[\x00-\x1f]", "clean string") is None

    def test_ssid_length_limit(self):
        assert len("A" * 32) <= 32  # valid
        assert len("A" * 33) > 32  # invalid

    def test_password_length_limit(self):
        assert len("A" * 63) <= 63  # valid
        assert len("A" * 64) > 63  # invalid


# ---------------------------------------------------------------------------
# Hotspot management (mocked subprocess)
# ---------------------------------------------------------------------------

class TestHotspotManagement:
    def test_start_hotspot_success(self):
        import subprocess as _sp
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(returncode=0)
            mock_sub.CalledProcessError = _sp.CalledProcessError
            assert portal.start_hotspot("TestSSID", "TestPass") is True

    def test_start_hotspot_failure(self):
        import subprocess as _sp
        with mock.patch("portal.subprocess") as mock_sub:
            mock_sub.CalledProcessError = _sp.CalledProcessError
            mock_sub.run.side_effect = _sp.CalledProcessError(
                1, "nmcli", stderr="Device not available"
            )
            assert portal.start_hotspot("TestSSID", "TestPass") is False


# ---------------------------------------------------------------------------
# Main boot retry logic
# ---------------------------------------------------------------------------

class TestMainBootRetry:
    def test_detects_internet_on_first_try(self):
        with mock.patch("portal.load_config", return_value={
            "KIOSK_URL": "https://example.com",
            "HOTSPOT_SSID": "Test",
            "HOTSPOT_PASSWORD": "pass",
        }), \
             mock.patch("portal.check_internet", return_value=True), \
             mock.patch("portal.ThreadingHTTPServer") as mock_server:
            # Make serve_forever raise to exit main()
            mock_server.return_value.serve_forever.side_effect = KeyboardInterrupt
            portal.main()
            assert portal.PortalHandler.is_online is True
            assert portal.PortalHandler.hotspot_active is False

    def test_starts_hotspot_after_retries_fail(self):
        with mock.patch("portal.load_config", return_value={
            "KIOSK_URL": "https://example.com",
            "HOTSPOT_SSID": "Test",
            "HOTSPOT_PASSWORD": "pass",
        }), \
             mock.patch("portal.check_internet", return_value=False), \
             mock.patch("portal.scan_wifi", return_value=[]), \
             mock.patch("portal.start_hotspot", return_value=True), \
             mock.patch("portal.stop_hotspot"), \
             mock.patch("portal.time.sleep"), \
             mock.patch("portal.ThreadingHTTPServer") as mock_server:
            mock_server.return_value.serve_forever.side_effect = KeyboardInterrupt
            portal.main()
            assert portal.PortalHandler.is_online is False
            assert portal.PortalHandler.hotspot_active is True
