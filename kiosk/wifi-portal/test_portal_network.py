"""Process boundary regressions for baseline 57cfcdc6867f."""

from unittest import mock

import logging
import subprocess
from unittest.mock import Mock, patch

import portal_network as network
import pytest


@pytest.mark.parametrize("failure", [None, OSError("device unavailable")])
def test_hotspot_stop_reports_command_outcome(failure):
    with patch.object(network.subprocess, "run", side_effect=failure):
        assert network.stop_hotspot() is (failure is None)


def test_status_failure_is_observable_without_exposing_command_data(caplog):
    with (
        patch.object(
            network.subprocess, "run", side_effect=OSError("private diagnostics")
        ),
        caplog.at_level(logging.WARNING),
    ):
        with pytest.raises(network.WifiOperationError, match="Unable to query"):
            network.get_connection_status()
    assert "connection status" in caplog.text.lower()
    assert "OSError" in caplog.text
    assert "private diagnostics" not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(
            1,
            ["nmcli", "password", "top-secret-password"],
            stderr="top-secret-password rejected",
        ),
        OSError("top-secret-password"),
    ],
)
def test_connection_failure_never_returns_credentials(failure, caplog):
    with patch.object(network.subprocess, "run", side_effect=failure):
        success, message = network.connect_wifi("Network", "top-secret-password")
    assert success is False
    assert "top-secret-password" not in message
    assert "top-secret-password" not in caplog.text
    assert message


def test_failed_connect_does_not_return_untrusted_stderr():
    listing = Mock(stdout="", returncode=0)
    failure = Mock(returncode=1, stderr="top-secret-password")
    with patch.object(network.subprocess, "run", side_effect=[listing, failure]):
        success, message = network.connect_wifi("Network", "top-secret-password")
    assert success is False
    assert "top-secret-password" not in message


def test_connection_timeout_logs_safe_operation_context(caplog):
    failure = subprocess.TimeoutExpired(
        ["nmcli", "password", "top-secret-password"],
        30,
        stderr="top-secret-password rejected",
    )
    with patch.object(network.subprocess, "run", side_effect=failure):
        assert network.connect_wifi("Network", "top-secret-password") == (
            False,
            "Connection timed out",
        )
    assert "WiFi connection failed" in caplog.text
    assert "TimeoutExpired" in caplog.text
    assert "top-secret-password" not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired(["nmcli", "password", "top-secret-password"], 15),
        FileNotFoundError("nmcli unavailable"),
    ],
)
def test_hotspot_failures_are_controlled(failure, caplog):
    with patch.object(network.subprocess, "run", side_effect=failure):
        assert network.start_hotspot("Setup", "top-secret-password") is False
    assert "top-secret-password" not in caplog.text


def test_nmcli_escaped_backslash_before_separator():
    assert network._parse_nmcli_fields(r"Network\\:wifi") == ["Network\\", "wifi"]


def test_connect_reuses_profile_with_escaped_name():
    listing = Mock(stdout=r"Office\:Guest:802-11-wireless", returncode=0)
    with (
        patch.object(
            network.subprocess, "run", side_effect=[listing, Mock(returncode=0)]
        ) as run,
        patch.object(network, "check_internet", return_value=True),
        patch.object(network.time, "sleep"),
    ):
        assert network.connect_wifi("Office:Guest", "")[0] is True
    assert run.call_args.args[0] == [
        "/usr/bin/nmcli",
        "connection",
        "up",
        "Office:Guest",
    ]


def test_scan_preserves_boundary_spaces_in_network_names():
    with patch.object(
        network.subprocess, "run", return_value=Mock(stdout=" Network :80:WPA2\n")
    ):
        assert network.scan_wifi() == [
            {"ssid": " Network ", "signal": 80, "security": "WPA2"}
        ]


def test_connect_reuses_profile_with_boundary_spaces():
    with (
        patch.object(
            network.subprocess,
            "run",
            side_effect=[
                Mock(stdout=" Network :802-11-wireless\n"),
                Mock(returncode=0),
            ],
        ) as run,
        patch.object(network, "check_internet", return_value=True),
        patch.object(network.time, "sleep"),
    ):
        assert network.connect_wifi(" Network ", "") == (True, "Connected")
    assert run.call_args.args[0] == ["/usr/bin/nmcli", "connection", "up", " Network "]


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("password", ["", "password123"])
def test_connect_selects_saved_or_new_profile_without_changing_credentials(
    existing, password
):
    listing = Mock(stdout="Network:802-11-wireless" if existing else "")
    with (
        patch.object(
            network.subprocess,
            "run",
            side_effect=[listing, Mock(returncode=0), Mock(returncode=0)],
        ) as run,
        patch.object(network, "check_internet", return_value=True),
        patch.object(network.time, "sleep"),
    ):
        assert network.connect_wifi("Network", password) == (True, "Connected")
    commands = [call.args[0] for call in run.call_args_list]
    if existing:
        assert commands[-1] == ["/usr/bin/nmcli", "connection", "up", "Network"]
        if password:
            assert commands[1] == [
                "/usr/bin/nmcli",
                "connection",
                "modify",
                "Network",
                "wifi-sec.psk",
                password,
            ]
        else:
            assert len(commands) == 2
    else:
        expected = [
            "/usr/bin/nmcli",
            "device",
            "wifi",
            "connect",
            "Network",
            "ifname",
            "wlan0",
        ]
        if password:
            expected += ["password", password]
        assert commands[-1] == expected


def test_wrong_connectivity_body_still_attempts_fallback():
    primary = Mock()
    primary.read.return_value = b"captive login page"
    fallback = Mock(status=204)
    with patch.object(
        network.urllib.request, "urlopen", side_effect=[primary, fallback]
    ):
        assert network.check_internet() is True
    primary.close.assert_called_once()
    fallback.close.assert_called_once()


class TestParseNmcliFields:
    def test_simple_fields(self):
        assert network._parse_nmcli_fields("a:b:c") == ["a", "b", "c"]

    def test_escaped_colons(self):
        assert network._parse_nmcli_fields(r"foo\:bar:baz") == ["foo:bar", "baz"]

    def test_multiple_escaped_colons(self):
        assert network._parse_nmcli_fields(r"a\:b\:c:d") == ["a:b:c", "d"]

    def test_empty_fields(self):
        assert network._parse_nmcli_fields("::") == ["", "", ""]

    def test_empty_string(self):
        assert network._parse_nmcli_fields("") == [""]

    def test_no_colons(self):
        assert network._parse_nmcli_fields("single") == ["single"]

    def test_trailing_colon(self):
        assert network._parse_nmcli_fields("a:b:") == ["a", "b", ""]

    def test_real_nmcli_wifi_line(self):
        # Real example: SSID:SIGNAL:SECURITY
        fields = network._parse_nmcli_fields("MyNetwork:85:WPA2")
        assert fields == ["MyNetwork", "85", "WPA2"]

    def test_ssid_with_colon(self):
        # SSIDs can contain colons
        fields = network._parse_nmcli_fields(r"My\:Network:75:WPA2")
        assert fields == ["My:Network", "75", "WPA2"]

    def test_backslash_not_before_colon(self):
        # Backslash not followed by colon should be preserved
        fields = network._parse_nmcli_fields(r"foo\nbar:baz")
        assert fields == ["foo\\nbar", "baz"]


class TestScanWifi:
    def test_parses_nmcli_output(self):
        fake_output = "Network1:85:WPA2\nNetwork2:60:WPA1 WPA2\nOpenNet:40:\n"
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = network.scan_wifi()

        assert len(networks) == 3
        # Sorted by signal descending
        assert networks[0]["ssid"] == "Network1"
        assert networks[0]["signal"] == 85
        assert networks[0]["security"] == "WPA2"
        assert networks[2]["ssid"] == "OpenNet"
        assert networks[2]["security"] == "Open"

    def test_deduplicates_ssids(self):
        fake_output = "DupeNet:80:WPA2\nDupeNet:60:WPA2\n"
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = network.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["ssid"] == "DupeNet"
        # Keeps first occurrence (higher signal since nmcli sorts)
        assert networks[0]["signal"] == 80

    def test_skips_empty_ssids(self):
        fake_output = ":80:WPA2\nRealNet:75:WPA2\n"
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = network.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["ssid"] == "RealNet"

    def test_handles_invalid_signal(self):
        fake_output = "Network:notanumber:WPA2\n"
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = network.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["signal"] == 0

    def test_handles_subprocess_failure(self):
        with (
            mock.patch("portal_network.subprocess") as mock_sub,
            pytest.raises(RuntimeError, match="Unable to scan WiFi") as raised,
        ):
            mock_sub.run.side_effect = OSError("nmcli not found")
            network.scan_wifi()
        assert isinstance(raised.value.__cause__, OSError)

    def test_handles_short_lines(self):
        fake_output = "TooShort:80\nGood:75:WPA2\n"
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=fake_output)
            networks = network.scan_wifi()

        assert len(networks) == 1
        assert networks[0]["ssid"] == "Good"


class TestGetConnectionStatus:
    def test_connected_with_ip(self):
        device_output = "wlan0:wifi:connected:MyNetwork\n"
        ip_output = "IP4.ADDRESS[1]:192.168.1.42/24\n"

        with (
            mock.patch("portal_network.subprocess") as mock_sub,
            mock.patch("portal_network.check_internet", return_value=True),
        ):
            mock_sub.run.side_effect = [
                mock.Mock(stdout=device_output),
                mock.Mock(stdout=ip_output),
            ]
            status = network.get_connection_status()

        assert status["connected"] is True
        assert status["ssid"] == "MyNetwork"
        assert status["ip"] == "192.168.1.42"
        assert status["internet"] is True

    def test_not_connected(self):
        device_output = "wlan0:wifi:disconnected:\n"

        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(stdout=device_output)
            status = network.get_connection_status()

        assert status["connected"] is False
        assert status["ssid"] == ""
        assert status["ip"] == ""

    def test_handles_subprocess_failure(self):
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.side_effect = OSError("nmcli failed")
            with pytest.raises(network.WifiOperationError, match="Unable to query"):
                network.get_connection_status()


class TestCheckInternet:
    def test_returns_true_on_success(self):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = network.CONNECTIVITY_BODY
        with mock.patch(
            "portal_network.urllib.request.urlopen", return_value=mock_resp
        ):
            assert network.check_internet() is True

    def test_returns_false_on_wrong_body(self):
        mock_resp = mock.Mock()
        mock_resp.read.return_value = b"something else"
        mock_resp_204 = mock.Mock()
        mock_resp_204.status = 500
        with mock.patch(
            "portal_network.urllib.request.urlopen",
            side_effect=[mock_resp, mock_resp_204],
        ):
            assert network.check_internet() is False

    def test_falls_back_to_gstatic(self):
        mock_resp_204 = mock.Mock()
        mock_resp_204.status = 204
        with mock.patch("portal_network.urllib.request.urlopen") as mock_url:
            # First call raises (Firefox portal down), second returns 204
            mock_url.side_effect = [OSError("timeout"), mock_resp_204]
            assert network.check_internet() is True

    def test_returns_false_when_both_fail(self):
        with mock.patch(
            "portal_network.urllib.request.urlopen", side_effect=OSError("no network")
        ):
            assert network.check_internet() is False


class TestHotspotManagement:
    def test_start_hotspot_success(self):
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.return_value = mock.Mock(returncode=0)
            assert network.start_hotspot("TestSSID", "TestPass") is True

    def test_start_hotspot_failure(self):
        with mock.patch("portal_network.subprocess") as mock_sub:
            mock_sub.run.side_effect = subprocess.CalledProcessError(
                1, "nmcli", stderr="Device not available"
            )
            assert network.start_hotspot("TestSSID", "TestPass") is False
