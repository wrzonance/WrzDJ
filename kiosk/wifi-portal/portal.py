#!/usr/bin/env python3
"""WrzDJ WiFi Captive Portal.

Single-file HTTP server (stdlib only) that acts as both a connectivity gateway
for the kiosk touchscreen and a captive portal for phones connecting to the
WrzDJ-Kiosk hotspot.

Boot flow:
  1. Check internet connectivity
  2. If connected → serve JS redirect to KIOSK_URL
  3. If not connected → pre-scan WiFi, start hotspot, serve setup UI
"""

import html as html_mod
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONF_FILE = "/etc/wrzdj-kiosk.conf"
DEFAULT_KIOSK_URL = "https://app.wrzdj.com/kiosk-pair"
DEFAULT_HOTSPOT_SSID = "WrzDJ-Kiosk"
DEFAULT_HOTSPOT_PASSWORD = "wrzdj1234"
PORTAL_IP = "10.42.0.1"
LISTEN_PORT = 80
CONNECTIVITY_URL = "http://detectportal.firefox.com/canonical.html"
CONNECTIVITY_BODY = b"<meta http-equiv=\"refresh\" content=\"0;url=https://support.mozilla.org/kb/captive-portal\"/>"

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("wifi-portal")


# ---------------------------------------------------------------------------
# Config parser (mirrors setup.sh's safe key-value parser)
# ---------------------------------------------------------------------------

_ALLOWED_KEYS = frozenset({
    "KIOSK_URL",
    "KIOSK_ROTATION",
    "EXTRA_CHROMIUM_FLAGS",
    "HOTSPOT_SSID",
    "HOTSPOT_PASSWORD",
})


def load_config():
    """Read key-value config from CONF_FILE. Returns a dict of known keys."""
    config = {
        "KIOSK_URL": DEFAULT_KIOSK_URL,
        "HOTSPOT_SSID": DEFAULT_HOTSPOT_SSID,
        "HOTSPOT_PASSWORD": DEFAULT_HOTSPOT_PASSWORD,
    }
    if not os.path.isfile(CONF_FILE):
        log.warning("Config file %s not found, using defaults", CONF_FILE)
        return config
    with open(CONF_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"')
            if key in _ALLOWED_KEYS:
                config[key] = value
    return config


# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------

def check_internet():
    """Return True if we can reach the internet."""
    try:
        resp = urllib.request.urlopen(CONNECTIVITY_URL, timeout=5)
        body = resp.read()
        return CONNECTIVITY_BODY in body
    except Exception:
        pass
    # Fallback: DNS + HTTP to a second endpoint
    try:
        resp = urllib.request.urlopen("http://www.gstatic.com/generate_204", timeout=5)
        return resp.status == 204
    except Exception:
        return False


# ---------------------------------------------------------------------------
# nmcli terse output parser
# ---------------------------------------------------------------------------

def _parse_nmcli_fields(line):
    """Parse nmcli -t output, handling \\: escapes for literal colons in values."""
    fields = []
    current = []
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == ":":
            current.append(":")
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


# ---------------------------------------------------------------------------
# WiFi scanning
# ---------------------------------------------------------------------------

def scan_wifi():
    """Scan available WiFi networks via nmcli. Returns list of dicts."""
    networks = []
    seen_ssids = set()
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().splitlines():
            parts = _parse_nmcli_fields(line)
            if len(parts) < 3:
                continue
            ssid = parts[0].strip()
            if not ssid or ssid in seen_ssids:
                continue
            seen_ssids.add(ssid)
            sig = 0
            try:
                sig = int(parts[1])
            except ValueError:
                pass  # nmcli printed no numeric signal; keep 0
            security = parts[2].strip() if parts[2].strip() else "Open"
            networks.append({
                "ssid": ssid,
                "signal": sig,
                "security": security,
            })
    except Exception as e:
        log.error("WiFi scan failed: %s", e)
    # Sort by signal strength descending
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


# ---------------------------------------------------------------------------
# Hotspot management
# ---------------------------------------------------------------------------

def start_hotspot(ssid, password):
    """Start WiFi hotspot via NetworkManager."""
    log.info("Starting hotspot")
    try:
        subprocess.run(
            ["nmcli", "device", "wifi", "hotspot",
             "ssid", ssid, "password", password, "ifname", "wlan0"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        log.info("Hotspot started")
        return True
    except subprocess.CalledProcessError as e:
        log.error("Failed to start hotspot: %s", e.stderr)
        return False


def stop_hotspot():
    """Stop the NM hotspot connection."""
    log.info("Stopping hotspot")
    try:
        subprocess.run(
            ["nmcli", "connection", "down", "Hotspot"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        log.warning("Hotspot stop: %s", e)


def _sanitize_nmcli_arg(value):
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


def connect_wifi(ssid, password):
    """Connect to a WiFi network. Returns (success, message)."""
    ssid = _sanitize_nmcli_arg(ssid)
    if password:
        _sanitize_nmcli_arg(password)
    log.info("Connecting to WiFi: %s", ssid)
    try:
        # Check if a connection profile already exists for this SSID
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=10,
        )
        existing = False
        for line in result.stdout.strip().splitlines():
            name, _, ctype = line.partition(":")
            if name == ssid and "wireless" in ctype:
                existing = True
                break

        if existing:
            # Update existing connection with new password if provided
            if password:
                subprocess.run(
                    ["nmcli", "connection", "modify", ssid,
                     "wifi-sec.psk", password],
                    capture_output=True, text=True, timeout=10, check=True,
                )
            result = subprocess.run(
                ["nmcli", "connection", "up", ssid],
                capture_output=True, text=True, timeout=30,
            )
        else:
            # Create new connection — omit password for open networks
            cmd = ["nmcli", "device", "wifi", "connect", ssid, "ifname", "wlan0"]
            if password:
                cmd.extend(["password", password])
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )

        if result.returncode == 0:
            # Verify internet connectivity
            time.sleep(2)
            if check_internet():
                return True, "Connected"
            # Wait a bit longer for DHCP
            time.sleep(3)
            if check_internet():
                return True, "Connected"
            return False, "Connected to WiFi but no internet access"
        return False, result.stderr.strip() or "Connection failed"
    except subprocess.TimeoutExpired:
        return False, "Connection timed out"
    except Exception as e:
        return False, str(e)


def get_connection_status():
    """Return current WiFi connection status."""
    status = {"connected": False, "ssid": "", "ip": "", "internet": False}
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION",
             "device", "status"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            parts = _parse_nmcli_fields(line)
            if len(parts) >= 4 and parts[1] == "wifi" and parts[2] == "connected":
                status["connected"] = True
                status["ssid"] = parts[3]
                break
    except Exception:
        pass  # nmcli missing/failed: report disconnected
    if status["connected"]:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                if "IP4.ADDRESS" in line:
                    # Format: IP4.ADDRESS[1]:192.168.1.5/24
                    addr = line.split(":", 1)[1].strip().split("/")[0]
                    status["ip"] = addr
                    break
        except Exception:
            pass  # nmcli missing/failed: leave ip blank
        status["internet"] = check_internet()
    return status


# ---------------------------------------------------------------------------
# HTML templates (embedded — no external files)
# ---------------------------------------------------------------------------

def _html_redirect(kiosk_url):
    """Page that redirects to the kiosk URL (shown when internet works)."""
    # Only allow http/https schemes — prevent javascript: injection
    if not re.match(r"^https?://", kiosk_url):
        log.error("Invalid KIOSK_URL scheme: %s — using default", kiosk_url)
        kiosk_url = DEFAULT_KIOSK_URL
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WrzDJ Kiosk</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#0a0a0a; color:#ededed;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    display:flex; align-items:center; justify-content:center;
    min-height:100vh; text-align:center; padding:2rem;
  }}
  .msg {{ font-size:1.2rem; opacity:0.7; }}
</style>
</head>
<body>
<div class="msg">Connecting to WrzDJ...</div>
<script>window.location.replace({json.dumps(kiosk_url)});</script>
</body>
</html>"""


def _html_setup(config, networks):
    """WiFi setup page for touchscreen and phone captive portal browser."""
    ssid = html_mod.escape(config.get("HOTSPOT_SSID", DEFAULT_HOTSPOT_SSID))
    password = html_mod.escape(config.get("HOTSPOT_PASSWORD", DEFAULT_HOTSPOT_PASSWORD))
    networks_json = json.dumps(networks)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>WrzDJ Kiosk Setup</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#0a0a0a; color:#ededed;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    min-height:100vh; padding:1.5rem;
  }}
  h1 {{
    font-size:1.6rem; text-align:center; margin-bottom:0.3rem;
    letter-spacing:-0.02em;
  }}
  .subtitle {{
    text-align:center; color:#888; font-size:0.9rem; margin-bottom:1.5rem;
  }}
  .card {{
    background:#1a1a1a; border-radius:12px; padding:1.2rem;
    margin-bottom:1rem; max-width:480px; margin-left:auto; margin-right:auto;
  }}
  .card h2 {{
    font-size:1rem; margin-bottom:0.8rem; color:#ccc;
  }}
  .network-list {{
    list-style:none; max-height:40vh; overflow-y:auto;
    -webkit-overflow-scrolling:touch;
  }}
  .network-item {{
    display:flex; align-items:center; justify-content:space-between;
    padding:0.9rem 0.7rem; border-bottom:1px solid #2a2a2a;
    cursor:pointer; border-radius:8px; transition:background 0.15s;
  }}
  .network-item:active, .network-item.selected {{
    background:#2a2a2a;
  }}
  .network-item:last-child {{ border-bottom:none; }}
  .ssid-name {{ font-size:1rem; font-weight:500; }}
  .signal-bars {{
    display:flex; align-items:flex-end; gap:2px; height:18px;
  }}
  .signal-bars .bar {{
    width:4px; background:#444; border-radius:1px;
  }}
  .signal-bars .bar.active {{ background:#4ade80; }}
  .security-badge {{
    font-size:0.65rem; color:#888; background:#222;
    padding:2px 5px; border-radius:3px; margin-left:0.5rem;
  }}
  .password-group {{
    display:flex; gap:0.5rem; margin-top:0.8rem;
  }}
  .password-group input {{
    flex:1; background:#111; border:1px solid #333; color:#ededed;
    padding:0.8rem; border-radius:8px; font-size:1rem;
    -webkit-appearance:none;
  }}
  .password-group input:focus {{
    outline:none; border-color:#4ade80;
  }}
  .btn {{
    display:block; width:100%; padding:0.9rem;
    background:#4ade80; color:#0a0a0a; border:none;
    border-radius:8px; font-size:1.05rem; font-weight:600;
    cursor:pointer; margin-top:0.8rem; transition:opacity 0.15s;
  }}
  .btn:disabled {{ opacity:0.4; cursor:not-allowed; }}
  .btn:active:not(:disabled) {{ opacity:0.8; }}
  .btn-secondary {{
    background:transparent; border:1px solid #333; color:#ededed;
    font-weight:400; font-size:0.9rem; margin-top:0.5rem;
  }}
  .status {{
    text-align:center; padding:1rem; font-size:0.95rem;
    display:none;
  }}
  .status.error {{ color:#f87171; }}
  .status.success {{ color:#4ade80; }}
  .status.connecting {{ color:#facc15; }}
  .hotspot-info {{
    text-align:center; color:#666; font-size:0.8rem;
    margin-top:1rem; line-height:1.5;
  }}
  .hotspot-info strong {{ color:#888; }}
  .empty-msg {{
    text-align:center; color:#666; padding:2rem 0; font-size:0.9rem;
  }}
  .manual-entry {{
    margin-top:0.8rem;
  }}
  .manual-entry input {{
    width:100%; background:#111; border:1px solid #333; color:#ededed;
    padding:0.8rem; border-radius:8px; font-size:1rem;
    -webkit-appearance:none;
  }}
  .manual-entry input:focus {{
    outline:none; border-color:#4ade80;
  }}
  .manual-entry label {{
    display:block; font-size:0.8rem; color:#888; margin-bottom:0.3rem;
  }}
</style>
</head>
<body>

<h1>WrzDJ Kiosk</h1>
<p class="subtitle">Connect to WiFi to get started</p>

<div class="card">
  <h2>Available Networks</h2>
  <ul class="network-list" id="networkList"></ul>
  <div class="manual-entry">
    <label for="manualSsid">Or enter network name manually:</label>
    <input type="text" id="manualSsid" placeholder="Network name (SSID)"
           autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
  </div>
  <button class="btn btn-secondary" id="rescanBtn" onclick="rescan()">
    Rescan Networks
  </button>
</div>

<div class="card">
  <h2>Password</h2>
  <div class="password-group">
    <input type="password" id="wifiPassword" placeholder="WiFi password"
           autocomplete="off" autocorrect="off" autocapitalize="off">
  </div>
  <button class="btn" id="connectBtn" onclick="connectWifi()" disabled>
    Connect
  </button>
</div>

<div class="status" id="status"></div>

<div class="hotspot-info">
  Connecting from your phone?<br>
  WiFi: <strong>{ssid}</strong> &middot; Password: <strong>{password}</strong>
</div>

<script>
var networks = {networks_json};
var selectedSsid = "";

function renderNetworks(list) {{
  var el = document.getElementById("networkList");
  if (!list.length) {{
    el.innerHTML = '<li class="empty-msg">No networks found. Tap Rescan.</li>';
    return;
  }}
  el.innerHTML = list.map(function(n) {{
    var bars = signalBars(n.signal);
    var sec = n.security !== "Open" ?
      '<span class="security-badge">' + esc(n.security) + '</span>' : '';
    return '<li class="network-item" onclick="selectNetwork(this, \\''+
      esc(n.ssid) + '\\')" data-ssid="' + esc(n.ssid) + '">' +
      '<span><span class="ssid-name">' + esc(n.ssid) + '</span>' + sec + '</span>' +
      '<span class="signal-bars">' + bars + '</span></li>';
  }}).join("");
}}

function signalBars(pct) {{
  var levels = [20, 40, 60, 80];
  return levels.map(function(thresh, i) {{
    var h = 4 + i * 4;
    var active = pct >= thresh ? " active" : "";
    return '<span class="bar' + active + '" style="height:' + h + 'px"></span>';
  }}).join("");
}}

function esc(s) {{
  var d = document.createElement("div");
  d.appendChild(document.createTextNode(s));
  return d.innerHTML;
}}

function selectNetwork(el, ssid) {{
  selectedSsid = ssid;
  document.getElementById("manualSsid").value = "";
  document.querySelectorAll(".network-item").forEach(function(item) {{
    item.classList.remove("selected");
  }});
  el.classList.add("selected");
  updateConnectBtn();
  document.getElementById("wifiPassword").focus();
}}

document.getElementById("manualSsid").addEventListener("input", function() {{
  if (this.value.trim()) {{
    selectedSsid = this.value.trim();
    document.querySelectorAll(".network-item").forEach(function(item) {{
      item.classList.remove("selected");
    }});
  }} else {{
    selectedSsid = "";
  }}
  updateConnectBtn();
}});

function updateConnectBtn() {{
  document.getElementById("connectBtn").disabled = !selectedSsid;
}}

function showStatus(msg, cls) {{
  var el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status " + cls;
  el.style.display = "block";
}}

function connectWifi() {{
  var ssid = selectedSsid;
  var pw = document.getElementById("wifiPassword").value;
  if (!ssid) return;

  showStatus("Connecting to " + ssid + "...", "connecting");
  document.getElementById("connectBtn").disabled = true;
  document.getElementById("rescanBtn").disabled = true;

  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/connect");
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.onload = function() {{
    try {{
      var resp = JSON.parse(xhr.responseText);
      if (resp.success) {{
        showStatus("Connected! Redirecting...", "success");
        setTimeout(function() {{ window.location.replace("/"); }}, 2000);
      }} else {{
        showStatus(resp.message || "Connection failed. Try again.", "error");
        document.getElementById("connectBtn").disabled = false;
        document.getElementById("rescanBtn").disabled = false;
      }}
    }} catch (e) {{
      showStatus("Unexpected error. Try again.", "error");
      document.getElementById("connectBtn").disabled = false;
      document.getElementById("rescanBtn").disabled = false;
    }}
  }};
  xhr.onerror = function() {{
    showStatus("Request failed. Hotspot may be restarting.", "error");
    setTimeout(function() {{
      window.location.replace("/");
    }}, 5000);
  }};
  xhr.timeout = 45000;
  xhr.ontimeout = function() {{
    showStatus("Timed out. Check password and try again.", "error");
    document.getElementById("connectBtn").disabled = false;
    document.getElementById("rescanBtn").disabled = false;
  }};
  xhr.send(JSON.stringify({{ssid: ssid, password: pw}}));
}}

function rescan() {{
  showStatus("Rescanning networks...", "connecting");
  document.getElementById("rescanBtn").disabled = true;
  var xhr = new XMLHttpRequest();
  xhr.open("GET", "/api/networks?rescan=1");
  xhr.onload = function() {{
    try {{
      var resp = JSON.parse(xhr.responseText);
      networks = resp.networks || [];
      renderNetworks(networks);
      document.getElementById("status").style.display = "none";
    }} catch (e) {{
      showStatus("Rescan failed.", "error");
    }}
    document.getElementById("rescanBtn").disabled = false;
  }};
  xhr.onerror = function() {{
    showStatus("Rescan failed. Hotspot restarting...", "connecting");
    document.getElementById("rescanBtn").disabled = false;
    setTimeout(function() {{ window.location.replace("/"); }}, 5000);
  }};
  xhr.timeout = 30000;
  xhr.send();
}}

renderNetworks(networks);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class PortalHandler(BaseHTTPRequestHandler):
    """Handles all HTTP requests for the captive portal."""

    # Shared state (set by main before server starts)
    config = {}
    cached_networks = []
    is_online = False
    hotspot_active = False
    lock = threading.Lock()

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

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/":
            return self._handle_root()
        if path == "/api/networks":
            return self._handle_networks()
        if path == "/api/status":
            return self._handle_status()
        # Captive portal detection paths — return 302 to root
        # This triggers the OS captive portal popup on phones
        return self._redirect(f"http://{PORTAL_IP}/")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/connect":
            self._handle_connect()
            return
        self._send_json({"error": "Not found"}, 404)

    def _handle_root(self):
        """Gateway: redirect to kiosk URL if online, otherwise show setup."""
        cls = type(self)
        with cls.lock:
            online = cls.is_online

        if not online:
            # Recheck — NM may have auto-reconnected to a saved network
            online = check_internet()
            if online:
                with cls.lock:
                    cls.is_online = True

        if online:
            kiosk_url = cls.config.get("KIOSK_URL", DEFAULT_KIOSK_URL)
            return self._send_html(_html_redirect(kiosk_url))

        # Offline — show setup page
        with cls.lock:
            networks = list(cls.cached_networks)
        return self._send_html(_html_setup(cls.config, networks))

    def _handle_networks(self):
        """Return cached WiFi scan results. ?rescan=1 triggers a new scan."""
        cls = type(self)
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        do_rescan = "rescan=1" in query

        if do_rescan:
            with cls.lock:
                was_hotspot = cls.hotspot_active

            if was_hotspot:
                # Must stop hotspot to scan, then restart
                stop_hotspot()
                time.sleep(2)

            networks = scan_wifi()

            with cls.lock:
                cls.cached_networks = networks

            if was_hotspot:
                ssid = cls.config.get("HOTSPOT_SSID", DEFAULT_HOTSPOT_SSID)
                pw = cls.config.get("HOTSPOT_PASSWORD", DEFAULT_HOTSPOT_PASSWORD)
                start_hotspot(ssid, pw)
        else:
            with cls.lock:
                networks = list(cls.cached_networks)

        return self._send_json({"networks": networks})

    def _handle_status(self):
        """Return current connection status."""
        status = get_connection_status()
        return self._send_json(status)

    def _handle_connect(self):
        """Stop hotspot, connect to selected WiFi, report result."""
        cls = type(self)
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0 or content_length > 4096:
            return self._send_json({"success": False, "message": "Invalid request"}, 400)

        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._send_json({"success": False, "message": "Invalid JSON"}, 400)

        ssid = data.get("ssid", "").strip()
        password = data.get("password", "")

        if not ssid:
            return self._send_json({"success": False, "message": "SSID is required"}, 400)
        # Sanitize: reject control characters in SSID/password
        if re.search(r"[\x00-\x1f]", ssid) or re.search(r"[\x00-\x1f]", password):
            return self._send_json(
                {"success": False, "message": "Invalid characters in input"}, 400
            )
        if len(ssid) > 32 or len(password) > 63:
            return self._send_json(
                {"success": False, "message": "SSID or password too long"}, 400
            )

        # Stop hotspot before connecting
        with cls.lock:
            if cls.hotspot_active:
                stop_hotspot()
                cls.hotspot_active = False
        time.sleep(1)

        success, message = connect_wifi(ssid, password)

        if success:
            with cls.lock:
                cls.is_online = True
            log.info("WiFi connected: %s", ssid)
            return self._send_json({"success": True, "message": "Connected"})

        # Connection failed — restart hotspot
        log.warning("WiFi connection failed: %s — restarting hotspot", message)
        hotspot_ssid = cls.config.get("HOTSPOT_SSID", DEFAULT_HOTSPOT_SSID)
        hotspot_pw = cls.config.get("HOTSPOT_PASSWORD", DEFAULT_HOTSPOT_PASSWORD)
        if start_hotspot(hotspot_ssid, hotspot_pw):
            with cls.lock:
                cls.hotspot_active = True
        return self._send_json({"success": False, "message": message})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    log.info("Portal starting")

    # Set shared state on handler class
    PortalHandler.config = config
    PortalHandler.cached_networks = []
    PortalHandler.is_online = False
    PortalHandler.hotspot_active = False

    # Check connectivity — retry for up to 30s to allow WiFi to connect on boot.
    # NetworkManager may still be bringing up a saved connection when we start.
    BOOT_WAIT_RETRIES = 10
    BOOT_WAIT_INTERVAL = 3  # seconds
    log.info("Checking internet connectivity (up to %ds)...",
             BOOT_WAIT_RETRIES * BOOT_WAIT_INTERVAL)
    online = False
    for attempt in range(1, BOOT_WAIT_RETRIES + 1):
        if check_internet():
            online = True
            break
        if attempt < BOOT_WAIT_RETRIES:
            log.info("  Attempt %d/%d — no internet yet, waiting %ds...",
                     attempt, BOOT_WAIT_RETRIES, BOOT_WAIT_INTERVAL)
            time.sleep(BOOT_WAIT_INTERVAL)

    if online:
        log.info("Internet available — portal will redirect to kiosk URL")
        PortalHandler.is_online = True
    else:
        log.info("No internet after %d attempts — scanning WiFi networks before starting hotspot...",
                 BOOT_WAIT_RETRIES)
        PortalHandler.cached_networks = scan_wifi()
        log.info("Found %d networks", len(PortalHandler.cached_networks))

        # Start hotspot
        ssid = config.get("HOTSPOT_SSID", DEFAULT_HOTSPOT_SSID)
        pw = config.get("HOTSPOT_PASSWORD", DEFAULT_HOTSPOT_PASSWORD)
        if start_hotspot(ssid, pw):
            PortalHandler.hotspot_active = True
        else:
            log.error("Failed to start hotspot — portal will serve setup page anyway")

    # Start threaded HTTP server (handles concurrent requests during
    # long-running operations like WiFi connect and rescan)
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), PortalHandler)
    server.daemon_threads = True
    log.info("Portal listening on 0.0.0.0:%d", LISTEN_PORT)

    def shutdown(signum, frame):
        log.info("Shutting down...")
        # Call server.shutdown() from a separate thread to avoid deadlock
        # (signal handler runs in main thread which may hold the server lock)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass  # Ctrl-C is a normal shutdown path; cleanup runs in finally
    finally:
        if PortalHandler.hotspot_active:
            stop_hotspot()
        server.server_close()
        log.info("Portal stopped")


if __name__ == "__main__":
    main()
