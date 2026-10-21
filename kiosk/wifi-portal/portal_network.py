"""NetworkManager operations and connectivity checks for the kiosk."""

import logging
import re
import subprocess
import time
import urllib.request
from contextlib import closing
from subprocess import SubprocessError, TimeoutExpired

from portal_types import ConnectionStatus, WifiNetwork

log = logging.getLogger("wifi-portal")

CONNECTIVITY_URL = "http://detectportal.firefox.com/canonical.html"
FALLBACK_CONNECTIVITY_URL = "http://www.gstatic.com/generate_204"


CONNECTIVITY_BODY = b'<meta http-equiv="refresh" content="0;url=https://support.mozilla.org/kb/captive-portal"/>'


class WifiOperationError(RuntimeError):
    """A radio operation failed with a safe message for setup clients."""


class WifiScanError(WifiOperationError):
    """A scan failed before it could produce a valid network list."""


def check_internet() -> bool:
    """Return True if we can reach the internet."""
    try:
        with closing(urllib.request.urlopen(CONNECTIVITY_URL, timeout=5)) as response:
            if CONNECTIVITY_BODY in response.read(4096):
                return True
    except OSError as error:
        log.debug("Primary connectivity probe failed (%s)", type(error).__name__)
    # Fallback: DNS + HTTP to a second endpoint
    try:
        with closing(
            urllib.request.urlopen(FALLBACK_CONNECTIVITY_URL, timeout=5)
        ) as response:
            return response.status == 204
    except OSError as error:
        log.debug("Fallback connectivity probe failed (%s)", type(error).__name__)
        return False


def _parse_nmcli_fields(line: str) -> list[str]:
    """Parse nmcli terse fields, unescaping literal colons and backslashes."""
    fields = []
    current = []
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] in ":\\":
            current.append(line[i + 1])
            i += 2
        elif line[i] == ":":
            fields.append("".join(current))
            current = []
            i += 1
        else:
            current.append(line[i])
            i += 1
    fields.append("".join(current))
    return fields


def _log_command_failure(operation: str, error: Exception) -> None:
    # Command arguments/stderr may contain credentials, so retain only safe context.
    log.warning(
        "%s failed (%s, exit=%s)",
        operation,
        type(error).__name__,
        getattr(error, "returncode", "unavailable"),
    )


def scan_wifi() -> list[WifiNetwork]:
    """Return networks from nmcli; raise WifiScanError if the scan fails."""
    networks: list[WifiNetwork] = []
    seen_ssids = set()
    try:
        result = subprocess.run(
            [
                "/usr/bin/nmcli",
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        for line in result.stdout.splitlines():
            parts = _parse_nmcli_fields(line)
            if len(parts) < 3:
                continue
            ssid = parts[0]
            if not ssid or ssid in seen_ssids:
                continue
            seen_ssids.add(ssid)
            sig = 0
            try:
                sig = int(parts[1])
            except ValueError:
                log.debug("WiFi scan returned an invalid signal strength; using zero")
            security = parts[2].strip() if parts[2].strip() else "Open"
            networks.append(
                {
                    "ssid": ssid,
                    "signal": sig,
                    "security": security,
                }
            )
    except (OSError, SubprocessError) as error:
        _log_command_failure("WiFi scan", error)
        raise WifiScanError("Unable to scan WiFi. Try again.") from error
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def start_hotspot(ssid: str, password: str) -> bool:
    """Start WiFi hotspot via NetworkManager."""
    log.info("Starting hotspot")
    try:
        subprocess.run(
            [
                "/usr/bin/nmcli",
                "device",
                "wifi",
                "hotspot",
                "ssid",
                ssid,
                "password",
                password,
                "ifname",
                "wlan0",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        log.info("Hotspot started")
        return True
    except (OSError, SubprocessError) as error:
        _log_command_failure("Hotspot start", error)
        return False


def stop_hotspot() -> bool:
    """Stop the NM hotspot connection and report confirmed success."""
    log.info("Stopping hotspot")
    try:
        subprocess.run(
            ["/usr/bin/nmcli", "connection", "down", "Hotspot"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return True
    except (OSError, SubprocessError) as error:
        _log_command_failure("Hotspot stop", error)
        return False


def _sanitize_nmcli_arg(value: str) -> str:
    """Validate a value is safe to pass as an nmcli argument.

    subprocess.run with a list already prevents shell injection, but this
    adds defense-in-depth by rejecting values with control characters or
    excessive length.
    """
    if not isinstance(value, str):
        raise ValueError("Expected string argument")
    if len(value) > 128:
        raise ValueError("Argument too long")
    if re.search(r"[\x00-\x1f]", value):
        raise ValueError("Control characters in argument")
    return value


def _has_wifi_profile(ssid: str) -> bool:
    result = subprocess.run(
        ["/usr/bin/nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    for line in result.stdout.splitlines():
        fields = _parse_nmcli_fields(line)
        if len(fields) == 2 and fields[0] == ssid and fields[1] == "802-11-wireless":
            return True
    return False


def _activate_wifi(ssid: str, password: str) -> int:
    if _has_wifi_profile(ssid):
        if password:
            subprocess.run(
                [
                    "/usr/bin/nmcli",
                    "connection",
                    "modify",
                    ssid,
                    "wifi-sec.psk",
                    password,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        command = ["/usr/bin/nmcli", "connection", "up", ssid]
    else:
        command = [
            "/usr/bin/nmcli",
            "device",
            "wifi",
            "connect",
            ssid,
            "ifname",
            "wlan0",
        ]
        if password:
            command.extend(["password", password])
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return result.returncode


def connect_wifi(ssid: str, password: str) -> tuple[bool, str]:
    """Connect to a WiFi network. Returns (success, safe user-facing message)."""
    ssid = _sanitize_nmcli_arg(ssid)
    if password:
        _sanitize_nmcli_arg(password)
    log.info("Connecting to WiFi: %s", ssid)
    try:
        returncode = _activate_wifi(ssid, password)
        if returncode:
            log.warning("WiFi connection failed (exit=%s)", returncode)
            return False, "Connection failed. Check the network name and password."
        # Give DHCP two bounded opportunities to establish connectivity.
        for delay in (2, 3):
            time.sleep(delay)
            if check_internet():
                return True, "Connected"
        return False, "Connected to WiFi but no internet access"
    except TimeoutExpired as error:
        _log_command_failure("WiFi connection", error)
        return False, "Connection timed out"
    except (OSError, SubprocessError) as error:
        _log_command_failure("WiFi connection", error)
        return False, "Unable to configure WiFi. Try again."


def get_connection_status() -> ConnectionStatus:
    """Return current WiFi connection status."""
    status: ConnectionStatus = {
        "connected": False,
        "ssid": "",
        "ip": "",
        "internet": False,
    }
    try:
        result = subprocess.run(
            [
                "/usr/bin/nmcli",
                "-t",
                "-f",
                "DEVICE,TYPE,STATE,CONNECTION",
                "device",
                "status",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        for line in result.stdout.splitlines():
            parts = _parse_nmcli_fields(line)
            if len(parts) >= 4 and parts[1] == "wifi" and parts[2] == "connected":
                status["connected"] = True
                status["ssid"] = parts[3]
                break
    except (OSError, SubprocessError) as error:
        _log_command_failure("Connection status", error)
        raise WifiOperationError("Unable to query WiFi connection status") from error
    if status["connected"]:
        try:
            result = subprocess.run(
                [
                    "/usr/bin/nmcli",
                    "-t",
                    "-f",
                    "IP4.ADDRESS",
                    "device",
                    "show",
                    "wlan0",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            for line in result.stdout.strip().splitlines():
                if "IP4.ADDRESS" in line:
                    # Format: IP4.ADDRESS[1]:192.168.1.5/24
                    addr = line.split(":", 1)[1].strip().split("/")[0]
                    status["ip"] = addr
                    break
        except (OSError, SubprocessError) as error:
            _log_command_failure("Connection IP address", error)
            raise WifiOperationError("Unable to query WiFi address") from error
        status["internet"] = check_internet()
    return status
