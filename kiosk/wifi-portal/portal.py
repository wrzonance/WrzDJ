#!/usr/bin/env python3
"""WrzDJ WiFi Captive Portal.

HTTP server (stdlib only) that acts as both a connectivity gateway
for the kiosk touchscreen and a captive portal for phones connecting to the
WrzDJ-Kiosk hotspot.

Boot flow:
  1. Check internet connectivity
  2. If connected → serve JS redirect to KIOSK_URL
  3. If not connected → pre-scan WiFi, start hotspot, serve setup UI
"""

import ipaddress
import json
import logging
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from portal_config import ConfigReadError, load_config
from portal_network import (
    WifiOperationError,
    WifiScanError,
    check_internet,
    connect_wifi,
    get_connection_status,
    scan_wifi,
    start_hotspot,
    stop_hotspot,
)
from portal_pages import html_redirect, html_setup
from portal_requests import MAX_REQUEST_BYTES, decode_connect_request
from portal_state import PortalState
from portal_types import WifiNetwork

PORTAL_IP = "10.42.0.1"
LISTEN_PORT = 80

log = logging.getLogger("wifi-portal")


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------


class PortalServer(ThreadingHTTPServer):
    """Serve requests using explicitly owned, independent runtime state."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: PortalState):
        self.state = state
        super().__init__(address, PortalHandler)


class PortalHandler(BaseHTTPRequestHandler):
    """Handles all HTTP requests for the captive portal."""

    server: PortalServer
    timeout = 5

    def _allow_setup_request(self, *, mutating=False):
        state = self.server.state
        try:
            client = ipaddress.ip_address(self.client_address[0])
            host = urlsplit("//" + self.headers.get("Host", ""))
            host_valid = host.hostname in {"localhost", "127.0.0.1", "::1", PORTAL_IP}
            origin = self.headers.get("Origin")
            origin_valid = (
                origin is None or urlsplit(origin).netloc.lower() == host.netloc.lower()
            )
        except ValueError:
            return False
        with state.lock:
            local_client = client.is_loopback or (
                state.hotspot_active and client in ipaddress.ip_network("10.42.0.0/24")
            )
            return (
                not state.stopping
                and local_client
                and host_valid
                and origin_valid
                and (not mutating or not state.is_online)
            )

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.client_address[0], fmt % args)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location, status=302):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path.startswith("/api/") and not self._allow_setup_request():
            return self._send_json(
                {"success": False, "message": "Setup access denied"}, 403
            )

        if path == "/api/ready":
            return self._send_json({"ready": True})
        if path == "/":
            return self._handle_root()
        if path == "/api/networks":
            return self._handle_networks()
        if path == "/api/status":
            return self._handle_status()
        # Captive portal detection paths — return 302 to root
        # This triggers the OS captive portal popup on phones
        return self._redirect(f"http://{PORTAL_IP}/")

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/connect":
            if not self._allow_setup_request(mutating=True):
                return self._send_json(
                    {"success": False, "message": "Setup access denied"}, 403
                )
            if self.headers.get_content_type() != "application/json":
                return self._send_json(
                    {"success": False, "message": "JSON required"}, 415
                )
            self._handle_connect()
            return
        self._send_json({"success": False, "message": "Not found"}, 404)

    def _handle_root(self):
        """Gateway: redirect to kiosk URL if online, otherwise show setup."""
        state = self.server.state
        with state.operation_lock:
            online = check_internet()
            with state.lock:
                state.is_online = online

        if online:
            kiosk_url = state.config["KIOSK_URL"]
            return self._send_html(html_redirect(kiosk_url))

        # Offline — show setup page
        if not self._allow_setup_request():
            return self._send_json(
                {"success": False, "message": "Setup access denied"}, 403
            )
        with state.lock:
            networks = list(state.cached_networks)
        return self._send_html(
            html_setup(
                state.config["HOTSPOT_SSID"],
                state.config["HOTSPOT_PASSWORD"],
                networks,
            )
        )

    def _handle_networks(self):
        """Return cached WiFi scan results. ?rescan=1 triggers a new scan."""
        state = self.server.state
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        do_rescan = parse_qs(query).get("rescan") == ["1"]

        if do_rescan:
            with state.operation_lock:
                if not self._allow_setup_request(mutating=True):
                    return self._send_json(
                        {"success": False, "message": "Setup access denied"}, 403
                    )
                try:
                    networks = self._rescan_networks()
                except WifiOperationError as error:
                    return self._send_json(
                        {"success": False, "message": str(error)}, 503
                    )
        else:
            with state.lock:
                networks = list(state.cached_networks)

        return self._send_json({"networks": networks})

    def _stop_active_hotspot(self) -> bool:
        """Return whether the radio is ready for scanning or connecting."""
        state = self.server.state
        with state.lock:
            was_active = state.hotspot_active
        if was_active:
            if not stop_hotspot():
                return False
            with state.lock:
                state.hotspot_active = False
        return True

    def _restore_hotspot(self) -> bool:
        state = self.server.state
        with state.lock:
            if state.stopping:
                return False
        active = start_hotspot(
            state.config["HOTSPOT_SSID"],
            state.config["HOTSPOT_PASSWORD"],
        )
        with state.lock:
            state.hotspot_active = active
        return active

    def _rescan_networks(self) -> list[WifiNetwork]:
        state = self.server.state
        with state.lock:
            was_hotspot = state.hotspot_active
        if not self._stop_active_hotspot():
            raise WifiOperationError("Unable to stop hotspot")
        scan_error: WifiOperationError | None = None
        try:
            if was_hotspot:
                time.sleep(2)
            networks = scan_wifi()
            with state.lock:
                state.cached_networks = networks
        except WifiOperationError as error:
            scan_error = error
        finally:
            restored = not was_hotspot or self._restore_hotspot()

        if not restored:
            message = (
                "Unable to restore setup hotspot. Use the kiosk screen to reconnect."
            )
            if scan_error is not None:
                message = f"{scan_error} {message}"
            raise WifiOperationError(message) from scan_error
        if scan_error is not None:
            raise scan_error
        return networks

    def _handle_status(self):
        """Return current connection status."""
        with self.server.state.operation_lock:
            if not self._allow_setup_request():
                return self._send_json(
                    {"success": False, "message": "Setup access denied"}, 403
                )
            try:
                status = get_connection_status()
            except WifiOperationError as error:
                return self._send_json({"success": False, "message": str(error)}, 503)
        return self._send_json(status)

    def _handle_connect(self):
        """Stop hotspot, connect to selected WiFi, report result."""
        state = self.server.state
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = 0
        if not 0 < content_length <= MAX_REQUEST_BYTES:
            return self._send_json(
                {"success": False, "message": "Invalid request"}, 400
            )

        try:
            ssid, password = decode_connect_request(self.rfile.read(content_length))
        except ValueError as error:
            return self._send_json({"success": False, "message": str(error)}, 400)

        with state.operation_lock:
            if not self._allow_setup_request(mutating=True):
                return self._send_json(
                    {"success": False, "message": "Setup access denied"}, 403
                )
            success, message = self._connect_network(ssid, password)
        return self._send_json({"success": success, "message": message})

    def _connect_network(self, ssid, password):
        state = self.server.state
        if not self._stop_active_hotspot():
            return False, "Unable to stop hotspot"
        time.sleep(1)

        success, message = connect_wifi(ssid, password)

        if success:
            with state.lock:
                state.is_online = True
            log.info("WiFi connected: %s", ssid)
            return True, "Connected"

        # Connection failed — restart hotspot
        log.warning("WiFi connection failed: %s — restarting hotspot", message)
        if not self._restore_hotspot():
            return False, f"{message} Setup hotspot could not be restored."
        return False, message


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _initialize_network(state: PortalState) -> None:
    config = state.config
    # Check connectivity — retry for up to 30s to allow WiFi to connect on boot.
    # NetworkManager may still be bringing up a saved connection when we start.
    BOOT_WAIT_RETRIES = 10
    BOOT_WAIT_INTERVAL = 3  # seconds
    log.info(
        "Checking internet connectivity (up to %ds)...",
        BOOT_WAIT_RETRIES * BOOT_WAIT_INTERVAL,
    )
    online = False
    for attempt in range(1, BOOT_WAIT_RETRIES + 1):
        if check_internet():
            online = True
            break
        if attempt < BOOT_WAIT_RETRIES:
            log.info(
                "  Attempt %d/%d — no internet yet, waiting %ds...",
                attempt,
                BOOT_WAIT_RETRIES,
                BOOT_WAIT_INTERVAL,
            )
            time.sleep(BOOT_WAIT_INTERVAL)

    if online:
        log.info("Internet available — portal will redirect to kiosk URL")
        state.is_online = True
    else:
        log.info(
            "No internet after %d attempts — scanning WiFi networks before starting hotspot...",
            BOOT_WAIT_RETRIES,
        )
        try:
            state.cached_networks = scan_wifi()
        except WifiScanError:
            log.info("Continuing setup with no cached networks after failed boot scan")
        log.info("Found %d networks", len(state.cached_networks))

        # Start hotspot
        if start_hotspot(
            config["HOTSPOT_SSID"],
            config["HOTSPOT_PASSWORD"],
        ):
            state.hotspot_active = True
        else:
            log.error("Failed to start hotspot — portal will serve setup page anyway")


def _serve_until_shutdown(server: PortalServer) -> None:
    def shutdown(signum, frame):
        log.info("Shutting down...")
        # Call server.shutdown() from a separate thread to avoid deadlock
        # (signal handler runs in main thread which may hold the server lock)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server.serve_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout
    )
    try:
        config = load_config()
    except ConfigReadError as error:
        log.error("%s (%s)", error, type(error.__cause__).__name__)
        raise SystemExit(1) from None
    state = PortalState(config)
    log.info("Portal starting")
    server: PortalServer | None = None

    try:
        _initialize_network(state)
        server = PortalServer(("0.0.0.0", LISTEN_PORT), state)
        log.info("Portal listening on 0.0.0.0:%d", LISTEN_PORT)
        _serve_until_shutdown(server)
    except KeyboardInterrupt:
        pass  # Ctrl-C is a normal shutdown path; cleanup runs in finally
    finally:
        with state.lock:
            state.stopping = True
        if server is not None:
            server.server_close()
        # In-flight radio operations own this lock. Drain them before cleanup,
        # while queued requests observe stopping and cannot start another one.
        with state.operation_lock:
            if state.hotspot_active and stop_hotspot():
                state.hotspot_active = False
        log.info("Portal stopped")


if __name__ == "__main__":
    main()
