"""Portal startup boundary tests (baseline 57cfcdc6867f)."""

import http.client
import threading
from queue import Queue
from unittest import mock

import portal
import portal_config
import portal_network
import pytest


def test_config_failure_stops_startup_with_safe_context(caplog):
    with (
        mock.patch.object(portal_config, "CONF_FILE", "/restricted/kiosk.conf"),
        mock.patch.object(portal_config.os.path, "isfile", return_value=True),
        mock.patch("builtins.open", side_effect=PermissionError("private diagnostics")),
        mock.patch.object(portal, "PortalServer") as server,
        mock.patch.object(portal, "start_hotspot") as hotspot,
        pytest.raises(SystemExit) as failure,
    ):
        portal.main()
    assert failure.value.code == 1
    assert "/restricted/kiosk.conf" in caplog.text
    assert "PermissionError" in caplog.text
    assert "private diagnostics" not in caplog.text
    server.assert_not_called()
    hotspot.assert_not_called()


def test_shutdown_cannot_leave_an_inflight_rescan_hotspot_running():
    """Baseline 57cfcdc6867f allowed request threads to restore WiFi after cleanup."""
    servers = Queue()
    scan_started = threading.Event()
    release_scan = threading.Event()
    listener_closed = threading.Event()
    errors = []
    radio_operations = []

    class LocalServer(portal.PortalServer):
        def __init__(self, address, state):
            super().__init__(("127.0.0.1", 0), state)
            servers.put(self)

        def server_close(self):
            super().server_close()
            listener_closed.set()

    def scan():
        if not scan_started.is_set():
            scan_started.set()
            assert release_scan.wait(timeout=3)
        return []

    def radio(operation):
        radio_operations.append(operation)
        return True

    def rescan(server):
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            connection.request("GET", "/api/networks?rescan=1")
            connection.getresponse().read()
        except Exception as error:
            errors.append(error)
        finally:
            connection.close()

    with (
        mock.patch("portal.PortalServer", LocalServer),
        mock.patch(
            "portal.load_config",
            return_value={
                "KIOSK_URL": "https://example.com",
                "HOTSPOT_SSID": "Setup",
                "HOTSPOT_PASSWORD": "password123",
            },
        ),
        mock.patch("portal.check_internet", return_value=False),
        mock.patch("portal.scan_wifi", side_effect=[[], mock.DEFAULT]) as scan_mock,
        mock.patch("portal.start_hotspot", side_effect=lambda *args: radio("start")),
        mock.patch("portal.stop_hotspot", side_effect=lambda: radio("stop")),
        mock.patch("portal.time.sleep"),
        mock.patch("portal.signal.signal"),
    ):
        main = threading.Thread(target=portal.main)
        main.start()
        server = servers.get(timeout=3)
        scan_mock.side_effect = scan
        request = threading.Thread(target=rescan, args=(server,))
        request.start()
        try:
            assert scan_started.wait(timeout=3)
            server.shutdown()
            assert listener_closed.wait(timeout=3)
        finally:
            release_scan.set()
            request.join(timeout=3)
            main.join(timeout=3)
        assert not request.is_alive()
        assert not main.is_alive()
    assert not errors
    assert radio_operations[-1] == "stop"
    assert radio_operations.count("start") == 1


class TestMainBootRetry:
    @pytest.mark.parametrize("failure_stage", ["bind", "signal"])
    def test_startup_failure_releases_resources(self, failure_stage):
        """Baseline 57cfcdc6867f leaked its hotspot if server setup failed."""
        with (
            mock.patch(
                "portal.load_config",
                return_value={
                    "KIOSK_URL": "https://example.com",
                    "HOTSPOT_SSID": "Setup",
                    "HOTSPOT_PASSWORD": "password123",
                },
            ),
            mock.patch("portal.check_internet", return_value=False),
            mock.patch("portal.scan_wifi", return_value=[]),
            mock.patch("portal.start_hotspot", return_value=True),
            mock.patch("portal.stop_hotspot") as stop,
            mock.patch("portal.time.sleep"),
            mock.patch("portal.PortalServer") as server,
            mock.patch("portal.signal.signal") as register_signal,
        ):
            failure = OSError("synthetic startup failure")
            if failure_stage == "bind":
                server.side_effect = failure
            else:
                register_signal.side_effect = failure
            with pytest.raises(OSError, match="synthetic startup failure"):
                portal.main()
        stop.assert_called_once()
        if failure_stage == "signal":
            server.return_value.server_close.assert_called_once()

    def test_scan_failure_still_starts_setup_hotspot(self):
        with (
            mock.patch(
                "portal.load_config",
                return_value={
                    "KIOSK_URL": "https://example.com",
                    "HOTSPOT_SSID": "Setup",
                    "HOTSPOT_PASSWORD": "password123",
                },
            ),
            mock.patch("portal.check_internet", return_value=False),
            mock.patch.object(
                portal_network.subprocess,
                "run",
                side_effect=OSError("device unavailable"),
            ),
            mock.patch("portal.start_hotspot", return_value=True) as start,
            mock.patch("portal.stop_hotspot"),
            mock.patch("portal.time.sleep"),
            mock.patch("portal.PortalServer") as server,
        ):
            server.return_value.serve_forever.side_effect = KeyboardInterrupt
            portal.main()
        start.assert_called_once_with("Setup", "password123")
        assert server.call_args.args[1].cached_networks == []
        server.return_value.server_close.assert_called_once()

    def test_detects_internet_on_first_try(self):
        with (
            mock.patch(
                "portal.load_config",
                return_value={
                    "KIOSK_URL": "https://example.com",
                    "HOTSPOT_SSID": "Test",
                    "HOTSPOT_PASSWORD": "pass",
                },
            ),
            mock.patch("portal.check_internet", return_value=True),
            mock.patch("portal.PortalServer") as mock_server,
        ):
            # Make serve_forever raise to exit main()
            mock_server.return_value.serve_forever.side_effect = KeyboardInterrupt
            portal.main()
            state = mock_server.call_args.args[1]
            assert state.is_online is True
            assert state.hotspot_active is False

    def test_starts_hotspot_after_retries_fail(self):
        with (
            mock.patch(
                "portal.load_config",
                return_value={
                    "KIOSK_URL": "https://example.com",
                    "HOTSPOT_SSID": "Test",
                    "HOTSPOT_PASSWORD": "pass",
                },
            ),
            mock.patch("portal.check_internet", return_value=False),
            mock.patch("portal.scan_wifi", return_value=[]),
            mock.patch("portal.start_hotspot", return_value=True),
            mock.patch("portal.stop_hotspot"),
            mock.patch("portal.time.sleep"),
            mock.patch("portal.PortalServer") as mock_server,
        ):
            mock_server.return_value.serve_forever.side_effect = KeyboardInterrupt
            portal.main()
            state = mock_server.call_args.args[1]
            assert state.is_online is False
            assert state.hotspot_active is False
