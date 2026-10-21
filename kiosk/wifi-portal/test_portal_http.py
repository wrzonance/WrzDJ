"""HTTP boundary regressions for baseline 57cfcdc6867f; radio calls are mocked."""

import http.client
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import Mock, patch

import portal
import portal_network
import pytest


@contextmanager
def running_portal(
    remote_address: str = "127.0.0.1",
) -> Iterator[tuple[int, portal.PortalState]]:
    state = portal.PortalState(
        {
            "KIOSK_URL": "https://example.com",
            "HOTSPOT_SSID": "Setup",
            "HOTSPOT_PASSWORD": "password123",
        },
        hotspot_active=True,
    )

    class Server(portal.PortalServer):
        def finish_request(self, connection, client_address):
            super().finish_request(connection, (remote_address, client_address[1]))

    server = Server(("127.0.0.1", 0), state)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield server.server_address[1], state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(
    port: int,
    method: str,
    path: str,
    body: str | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        request_headers = (
            {"Content-Type": "application/json"} if body is not None else {}
        )
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


@pytest.mark.parametrize("query", ["device", "address"])
def test_status_query_failure_is_unavailable_without_private_diagnostics(query):
    results = [OSError("private command diagnostics")]
    if query == "address":
        results.insert(0, Mock(stdout="wlan0:wifi:connected:Network\n"))
    with (
        patch.object(portal_network.subprocess, "run", side_effect=results),
        patch.object(portal_network, "check_internet", return_value=False),
        running_portal() as (port, _),
    ):
        status, body = request(port, "GET", "/api/status")
    assert status == 503
    payload = json.loads(body)
    assert payload["success"] is False
    assert "Unable to query" in payload["message"]
    assert "private command diagnostics" not in body


def test_status_snapshot_finishes_before_connect_changes_the_radio():
    """Regression for 57cfcdc6867f: never mix an old SSID with a new IP."""
    status_started = threading.Event()
    release_status = threading.Event()
    transition_attempted = threading.Event()
    radio = {"ssid": "Old network", "ip": "192.168.1.10"}
    responses = {}
    errors = []

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if self.lock.locked():
                transition_attempted.set()
            self.lock.acquire()

        def __exit__(self, *exception):
            self.lock.release()

    def status_query():
        ssid = radio["ssid"]
        status_started.set()
        assert release_status.wait(timeout=1)
        return {"ssid": ssid, "ip": radio["ip"], "online": False}

    def connect(ssid, password):
        radio.update(ssid=ssid, ip="192.168.2.20")
        transition_attempted.set()
        return True, "Connected"

    def send(name, port, method, path, body=None):
        try:
            responses[name] = request(port, method, path, body)
        except Exception as error:
            errors.append(error)

    with (
        patch.object(portal, "get_connection_status", status_query),
        patch.object(portal, "connect_wifi", connect),
        patch.object(portal, "stop_hotspot", return_value=True),
        patch.object(portal.time, "sleep"),
        running_portal() as (port, state),
    ):
        state.operation_lock = ObservedLock()
        status_thread = threading.Thread(
            target=send, args=("status", port, "GET", "/api/status")
        )
        connect_thread = threading.Thread(
            target=send,
            args=(
                "connect",
                port,
                "POST",
                "/api/connect",
                json.dumps({"ssid": "New network"}),
            ),
        )
        status_thread.start()
        try:
            assert status_started.wait(timeout=1)
            connect_thread.start()
            assert transition_attempted.wait(timeout=1)
        finally:
            release_status.set()
            status_thread.join(timeout=2)
            if connect_thread.ident is not None:
                connect_thread.join(timeout=2)

    assert not errors
    assert not status_thread.is_alive()
    assert not connect_thread.is_alive()
    status_code, body = responses["status"]
    assert status_code == 200
    assert json.loads(body) == {
        "ssid": "Old network",
        "ip": "192.168.1.10",
        "online": False,
    }
    assert responses["connect"][0] == 200
    assert json.loads(responses["connect"][1])["success"] is True
    assert radio == {"ssid": "New network", "ip": "192.168.2.20"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        42,
        "ssid",
        {"ssid": 12},
        {"ssid": None},
        {"ssid": "Network", "password": None},
        {"ssid": "Network", "password": []},
        {"ssid": "Network", "password": 12},
        {"ssid": "é" * 17},
        {"ssid": "\ud800"},
        {"ssid": "hello\x00world"},
        {"ssid": "hello\nworld"},
        {"ssid": "hello\tworld"},
        {"ssid": "A" * 33},
        {"ssid": "Network", "password": "A" * 64},
    ],
)
def test_invalid_connect_payload_cannot_change_radio(payload):
    with (
        patch.object(portal, "connect_wifi") as connect,
        patch.object(portal, "stop_hotspot") as stop,
        running_portal() as (port, _),
    ):
        status, body = request(port, "POST", "/api/connect", json.dumps(payload))
    assert status == 400
    assert json.loads(body)["success"] is False
    connect.assert_not_called()
    stop.assert_not_called()


@pytest.mark.parametrize("length", ["invalid", "-1", "0", "4097"])
def test_invalid_content_length_is_rejected(length):
    with patch.object(portal, "connect_wifi") as connect, running_portal() as (port, _):
        status, body = request(
            port, "POST", "/api/connect", b"{}", {"Content-Length": length}
        )
    assert status == 400
    assert json.loads(body)["success"] is False
    connect.assert_not_called()


def test_connect_preserves_ssid_whitespace():
    connect = Mock(return_value=(True, "Connected"))
    with (
        patch.object(portal, "connect_wifi", connect),
        patch.object(portal, "stop_hotspot"),
        patch.object(portal.time, "sleep"),
        running_portal() as (port, _),
    ):
        status, body = request(
            port,
            "POST",
            "/api/connect",
            json.dumps({"ssid": " Network ", "password": "secret123"}),
        )
    assert status == 200
    assert json.loads(body)["success"] is True
    connect.assert_called_once_with(" Network ", "secret123")


def test_root_recovers_setup_page_after_losing_connectivity():
    with (
        patch.object(portal, "check_internet", return_value=False),
        running_portal() as (port, state),
    ):
        state.is_online = True
        status, body = request(port, "GET", "/")
    assert status == 200
    assert "Available Networks" in body
    assert state.is_online is False


def test_readiness_endpoint_responds_while_gateway_probe_is_blocked():
    probe_started = threading.Event()
    release_probe = threading.Event()
    root_responses = []
    root_errors = []

    def blocked_probe():
        probe_started.set()
        assert release_probe.wait(timeout=3)
        return False

    def request_root(port):
        try:
            root_responses.append(request(port, "GET", "/"))
        except Exception as error:
            root_errors.append(error)

    with (
        patch.object(portal, "check_internet", side_effect=blocked_probe),
        running_portal() as (
            port,
            _,
        ),
    ):
        root_thread = threading.Thread(target=request_root, args=(port,))
        root_thread.start()
        try:
            assert probe_started.wait(timeout=1)
            status, body = request(port, "GET", "/api/ready")
        finally:
            release_probe.set()
            root_thread.join(timeout=2)

    assert not root_thread.is_alive()
    assert not root_errors
    assert root_responses and root_responses[0][0] == 200
    assert status == 200
    assert json.loads(body) == {"ready": True}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/ready"),
        ("GET", "/api/networks"),
        ("GET", "/api/status"),
        ("POST", "/api/connect"),
    ],
)
def test_other_lan_clients_cannot_configure_wifi(method, path):
    with (
        patch.object(portal, "connect_wifi") as connect,
        patch.object(portal, "get_connection_status") as status_query,
        running_portal("192.168.1.50") as (port, _),
    ):
        status, body = request(port, method, path, json.dumps({"ssid": "Network"}))
    assert status == 403
    assert json.loads(body) == {"success": False, "message": "Setup access denied"}
    connect.assert_not_called()
    status_query.assert_not_called()


def test_unknown_post_uses_the_same_error_contract():
    with running_portal() as (port, _):
        status, body = request(port, "POST", "/api/missing", "{}")
    assert status == 404
    assert json.loads(body) == {"success": False, "message": "Not found"}


def test_servers_keep_separate_network_cache_config_and_operation_lock():
    """Baseline 57cfcdc6867f stored mutable state on the shared handler class."""
    first_state = portal.PortalState(
        {
            "KIOSK_URL": "https://first.example",
            "HOTSPOT_SSID": "First setup",
            "HOTSPOT_PASSWORD": "first-secret",
        }
    )
    second_state = portal.PortalState(
        {
            "KIOSK_URL": "https://second.example",
            "HOTSPOT_SSID": "Second setup",
            "HOTSPOT_PASSWORD": "second-secret",
        }
    )
    first_state.cached_networks.append(
        {"ssid": "First network", "signal": 80, "security": "Open"}
    )
    with (
        portal.PortalServer(("127.0.0.1", 0), first_state) as first,
        portal.PortalServer(("127.0.0.1", 0), second_state) as second,
        patch.object(portal, "check_internet", return_value=False),
    ):
        threads = [
            threading.Thread(target=server.serve_forever) for server in (first, second)
        ]
        for thread in threads:
            thread.start()
        try:
            with first_state.operation_lock:
                status, body = request(second.server_address[1], "GET", "/")
                assert status == 200
                assert "Second setup" in body
                assert "first-secret" not in body
            assert (
                json.loads(request(first.server_address[1], "GET", "/api/networks")[1])[
                    "networks"
                ]
                == first_state.cached_networks
            )
            assert json.loads(
                request(second.server_address[1], "GET", "/api/networks")[1]
            ) == {"networks": []}
        finally:
            first.shutdown()
            second.shutdown()
            for thread in threads:
                thread.join(timeout=2)


def test_online_portal_rejects_network_changes():
    with (
        patch.object(portal, "connect_wifi") as connect,
        running_portal() as (port, state),
    ):
        state.is_online = True
        status, _ = request(
            port, "POST", "/api/connect", json.dumps({"ssid": "Network"})
        )
    assert status == 403
    connect.assert_not_called()


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://untrusted.example"}, {"Content-Type": "text/plain"}]
)
def test_cross_origin_connect_is_rejected(headers):
    with patch.object(portal, "connect_wifi") as connect, running_portal() as (port, _):
        status, _ = request(
            port, "POST", "/api/connect", json.dumps({"ssid": "Network"}), headers
        )
    assert status in (403, 415)
    connect.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "untrusted.example"},
        {"Origin": "https://untrusted.example"},
    ],
)
def test_readiness_endpoint_rejects_untrusted_host_or_origin(headers):
    with running_portal() as (port, _):
        status, body = request(port, "GET", "/api/ready", headers=headers)
    assert status == 403
    assert json.loads(body) == {"success": False, "message": "Setup access denied"}


def test_failed_connection_restores_hotspot_and_reports_actual_state():
    with (
        patch.object(portal, "connect_wifi", return_value=(False, "Connection failed")),
        patch.object(portal, "stop_hotspot"),
        patch.object(portal.time, "sleep"),
        patch.object(portal, "start_hotspot", return_value=False),
        running_portal() as (port, state),
    ):
        status, body = request(
            port, "POST", "/api/connect", json.dumps({"ssid": "Network"})
        )
    assert status == 200
    assert json.loads(body)["success"] is False
    assert "hotspot could not be restored" in json.loads(body)["message"].lower()
    assert state.hotspot_active is False


def test_rescan_updates_hotspot_state_after_failed_restart():
    with (
        patch.object(portal, "scan_wifi", return_value=[]),
        patch.object(portal, "stop_hotspot"),
        patch.object(portal.time, "sleep"),
        patch.object(portal, "start_hotspot", return_value=False),
        running_portal() as (port, state),
    ):
        status, body = request(port, "GET", "/api/networks?rescan=1")
    assert status == 503
    assert json.loads(body) == {
        "success": False,
        "message": "Unable to restore setup hotspot. Use the kiosk screen to reconnect.",
    }
    assert state.hotspot_active is False


@pytest.mark.parametrize("hotspot_restored", [True, False])
def test_failed_rescan_preserves_cache_and_reports_both_radio_outcomes(
    hotspot_restored,
):
    """Regression for 57cfcdc6867f: failed cleanup must not hide a failed scan."""
    with (
        patch.object(
            portal_network.subprocess,
            "run",
            side_effect=OSError("private device detail"),
        ),
        patch.object(portal, "stop_hotspot", return_value=True),
        patch.object(portal.time, "sleep"),
        patch.object(portal, "start_hotspot", return_value=hotspot_restored) as restart,
        running_portal() as (port, state),
    ):
        previous = [{"ssid": "Known network", "signal": 80, "security": "WPA2"}]
        state.cached_networks = previous
        status, body = request(port, "GET", "/api/networks?rescan=1")
    assert status == 503
    expected_message = "Unable to scan WiFi. Try again."
    if not hotspot_restored:
        expected_message += (
            " Unable to restore setup hotspot. Use the kiosk screen to reconnect."
        )
    assert json.loads(body) == {"success": False, "message": expected_message}
    assert "private device detail" not in body
    assert state.cached_networks == previous
    assert state.hotspot_active is hotspot_restored
    restart.assert_called_once_with("Setup", "password123")


@pytest.mark.parametrize("operation", ["connect", "rescan"])
def test_failed_hotspot_stop_preserves_state_and_aborts_radio_change(operation):
    with (
        patch.object(portal, "stop_hotspot", return_value=False),
        patch.object(
            portal, "connect_wifi", return_value=(True, "Connected")
        ) as connect,
        patch.object(portal, "scan_wifi", return_value=[]) as scan,
        patch.object(portal, "start_hotspot") as restart,
        patch.object(portal.time, "sleep"),
        running_portal() as (port, state),
    ):
        if operation == "connect":
            status, body = request(
                port, "POST", "/api/connect", json.dumps({"ssid": "Network"})
            )
            assert status == 200
            assert json.loads(body)["success"] is False
        else:
            status, body = request(port, "GET", "/api/networks?rescan=1")
            assert status == 503
        assert "hotspot" in body.lower()
        assert state.hotspot_active is True
        connect.assert_not_called()
        scan.assert_not_called()
        restart.assert_not_called()


def test_connect_waits_for_rescan_and_keeps_hotspot_off_on_success():
    scan_started = threading.Event()
    release_scan = threading.Event()
    connect_started = threading.Event()
    connect_waiting = threading.Event()
    errors = []

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if self.lock.locked():
                connect_waiting.set()
            self.lock.acquire()

        def __exit__(self, *exception):
            self.lock.release()

    def scan():
        scan_started.set()
        assert release_scan.wait(timeout=1)
        return []

    def connect(ssid, password):
        connect_started.set()
        return True, "Connected"

    def send(port, method, path, body=None):
        try:
            request(port, method, path, body)
        except Exception as error:
            errors.append(error)

    with (
        patch.object(portal, "scan_wifi", scan),
        patch.object(portal, "connect_wifi", connect),
        patch.object(portal, "stop_hotspot"),
        patch.object(portal.time, "sleep"),
        patch.object(portal, "start_hotspot", return_value=True),
        running_portal() as (port, state),
    ):
        state.operation_lock = ObservedLock()
        rescan = threading.Thread(
            target=send, args=(port, "GET", "/api/networks?rescan=1")
        )
        rescan.start()
        assert scan_started.wait(timeout=1)
        connection = threading.Thread(
            target=send,
            args=(port, "POST", "/api/connect", json.dumps({"ssid": "Network"})),
        )
        connection.start()
        try:
            assert connect_waiting.wait(timeout=1)
            assert not connect_started.is_set()
        finally:
            release_scan.set()
            rescan.join(timeout=2)
            connection.join(timeout=2)
    assert not errors
    assert state.is_online is True
    assert state.hotspot_active is False
