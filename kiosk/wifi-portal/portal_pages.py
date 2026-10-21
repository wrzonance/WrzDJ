"""Standalone HTML rendering for the stdlib kiosk portal."""

import html as html_mod
import json
import logging
import re

from portal_defaults import DEFAULT_KIOSK_URL
from portal_types import WifiNetwork

log = logging.getLogger("wifi-portal")


def _script_json(value):
    """Serialize data without allowing HTML to terminate its script element."""
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def html_redirect(kiosk_url: str) -> str:
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
<script>window.location.replace({_script_json(kiosk_url)});</script>
</body>
</html>"""


SETUP_STYLES = """
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background:#0a0a0a; color:#ededed;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    min-height:100vh; padding:1.5rem;
  }
  h1 {
    font-size:1.6rem; text-align:center; margin-bottom:0.3rem;
    letter-spacing:-0.02em;
  }
  .subtitle {
    text-align:center; color:#888; font-size:0.9rem; margin-bottom:1.5rem;
  }
  .card {
    background:#1a1a1a; border-radius:12px; padding:1.2rem;
    margin-bottom:1rem; max-width:480px; margin-left:auto; margin-right:auto;
  }
  .card h2 {
    font-size:1rem; margin-bottom:0.8rem; color:#ccc;
  }
  .network-list {
    list-style:none; max-height:40vh; overflow-y:auto;
    -webkit-overflow-scrolling:touch;
  }
  .network-item {
    display:flex; align-items:center; justify-content:space-between;
    padding:0.9rem 0.7rem; border-bottom:1px solid #2a2a2a;
    cursor:pointer; border-radius:8px; transition:background 0.15s;
  }
  .network-item:active, .network-item.selected {
    background:#2a2a2a;
  }
  .network-item:last-child { border-bottom:none; }
  .network-label { min-width:0; overflow-wrap:anywhere; }
  .ssid-name { font-size:1rem; font-weight:500; }
  .signal-bars {
    display:flex; align-items:flex-end; gap:2px; height:18px;
    flex-shrink:0; margin-left:0.5rem;
  }
  .signal-bars .bar {
    width:4px; background:#444; border-radius:1px;
  }
  .signal-bars .bar.active { background:#4ade80; }
  .security-badge {
    font-size:0.65rem; color:#888; background:#222;
    padding:2px 5px; border-radius:3px; margin-left:0.5rem;
  }
  .password-group {
    display:flex; gap:0.5rem; margin-top:0.8rem;
  }
  .password-group input {
    flex:1; background:#111; border:1px solid #333; color:#ededed;
    padding:0.8rem; border-radius:8px; font-size:1rem;
    -webkit-appearance:none;
  }
  .password-group input:focus {
    outline:none; border-color:#4ade80;
  }
  .btn {
    display:block; width:100%; padding:0.9rem;
    background:#4ade80; color:#0a0a0a; border:none;
    border-radius:8px; font-size:1.05rem; font-weight:600;
    cursor:pointer; margin-top:0.8rem; transition:opacity 0.15s;
  }
  .btn:disabled { opacity:0.4; cursor:not-allowed; }
  .btn:active:not(:disabled) { opacity:0.8; }
  .btn-secondary {
    background:transparent; border:1px solid #333; color:#ededed;
    font-weight:400; font-size:0.9rem; margin-top:0.5rem;
  }
  .status {
    text-align:center; padding:1rem; font-size:0.95rem;
    display:none;
  }
  .status.error { color:#f87171; }
  .status.success { color:#4ade80; }
  .status.connecting { color:#facc15; }
  .hotspot-info {
    text-align:center; color:#666; font-size:0.8rem;
    margin-top:1rem; line-height:1.5;
  }
  .hotspot-info strong { color:#888; }
  .empty-msg {
    text-align:center; color:#666; padding:2rem 0; font-size:0.9rem;
  }
  .manual-entry {
    margin-top:0.8rem;
  }
  .manual-entry input {
    width:100%; background:#111; border:1px solid #333; color:#ededed;
    padding:0.8rem; border-radius:8px; font-size:1rem;
    -webkit-appearance:none;
  }
  .manual-entry input:focus {
    outline:none; border-color:#4ade80;
  }
  .manual-entry label {
    display:block; font-size:0.8rem; color:#888; margin-bottom:0.3rem;
  }
"""

SETUP_SCRIPT = """
var selectedSsid = "";

function renderNetworks(list) {
  var el = document.getElementById("networkList");
  el.replaceChildren();
  if (!list.length) {
    var empty = document.createElement("li");
    empty.className = "empty-msg";
    empty.textContent = "No networks found. Tap Rescan.";
    el.appendChild(empty);
    return;
  }
  list.forEach(function(n) {
    var item = document.createElement("li");
    item.className = "network-item";
    item.dataset.ssid = n.ssid;
    item.addEventListener("click", function() { selectNetwork(item, n.ssid); });
    var label = document.createElement("span");
    label.className = "network-label";
    var name = document.createElement("span");
    name.className = "ssid-name";
    name.textContent = n.ssid;
    label.appendChild(name);
    if (n.security !== "Open") {
      var security = document.createElement("span");
      security.className = "security-badge";
      security.textContent = n.security;
      label.appendChild(security);
    }
    item.appendChild(label);
    item.appendChild(signalBars(n.signal));
    el.appendChild(item);
  });
}

function signalBars(pct) {
  var bars = document.createElement("span");
  bars.className = "signal-bars";
  [20, 40, 60, 80].forEach(function(thresh, i) {
    var bar = document.createElement("span");
    bar.className = "bar" + (pct >= thresh ? " active" : "");
    bar.style.height = (4 + i * 4) + "px";
    bars.appendChild(bar);
  });
  return bars;
}

function selectNetwork(el, ssid) {
  selectedSsid = ssid;
  document.getElementById("manualSsid").value = "";
  document.querySelectorAll(".network-item").forEach(function(item) {
    item.classList.remove("selected");
  });
  el.classList.add("selected");
  updateConnectBtn();
  document.getElementById("wifiPassword").focus();
}

document.getElementById("manualSsid").addEventListener("input", function() {
  if (this.value) {
    selectedSsid = this.value;
    document.querySelectorAll(".network-item").forEach(function(item) {
      item.classList.remove("selected");
    });
  } else {
    selectedSsid = "";
  }
  updateConnectBtn();
});

function updateConnectBtn() {
  document.getElementById("connectBtn").disabled = !selectedSsid;
}

function showStatus(msg, cls) {
  var el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status " + cls;
  el.style.display = "block";
}

function connectWifi() {
  var ssid = selectedSsid;
  var password = document.getElementById("wifiPassword").value;
  if (!ssid) return;

  showStatus("Connecting to " + ssid + "...", "connecting");
  document.getElementById("connectBtn").disabled = true;
  document.getElementById("rescanBtn").disabled = true;

  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/connect");
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.onload = function() {
    try {
      var resp = JSON.parse(xhr.responseText);
      if (resp.success) {
        showStatus("Connected! Redirecting...", "success");
        setTimeout(function() { window.location.replace("/"); }, 2000);
      } else {
        showStatus(resp.message || "Connection failed. Try again.", "error");
        document.getElementById("connectBtn").disabled = false;
        document.getElementById("rescanBtn").disabled = false;
      }
    } catch (e) {
      showStatus("Unexpected error. Try again.", "error");
      document.getElementById("connectBtn").disabled = false;
      document.getElementById("rescanBtn").disabled = false;
    }
  };
  xhr.onerror = function() {
    showStatus("Request failed. Hotspot may be restarting.", "error");
    setTimeout(function() {
      window.location.replace("/");
    }, 5000);
  };
  xhr.timeout = 45000;
  xhr.ontimeout = function() {
    showStatus("Timed out. Check password and try again.", "error");
    document.getElementById("connectBtn").disabled = false;
    document.getElementById("rescanBtn").disabled = false;
  };
  xhr.send(JSON.stringify({ssid: ssid, password: password}));
}

function rescan() {
  showStatus("Rescanning networks...", "connecting");
  document.getElementById("rescanBtn").disabled = true;
  var xhr = new XMLHttpRequest();
  xhr.open("GET", "/api/networks?rescan=1");
  xhr.onload = function() {
    try {
      var resp = JSON.parse(xhr.responseText);
      if (xhr.status < 200 || xhr.status >= 300 || resp.success === false || !Array.isArray(resp.networks)) {
        showStatus(resp.message || "Rescan failed.", "error");
      } else {
        networks = resp.networks;
        renderNetworks(networks);
        document.getElementById("status").style.display = "none";
      }
    } catch (e) {
      showStatus("Rescan failed.", "error");
    }
    document.getElementById("rescanBtn").disabled = false;
  };
  xhr.onerror = function() {
    showStatus("Rescan failed. Hotspot restarting...", "connecting");
    document.getElementById("rescanBtn").disabled = false;
    setTimeout(function() { window.location.replace("/"); }, 5000);
  };
  xhr.timeout = 30000;
  xhr.ontimeout = function() {
    showStatus("Rescan timed out. Try again.", "error");
    document.getElementById("rescanBtn").disabled = false;
  };
  xhr.send();
}

renderNetworks(networks);
"""


def html_setup(
    hotspot_ssid: str, hotspot_password: str, networks: list[WifiNetwork]
) -> str:
    """WiFi setup page for touchscreen and phone captive portal browser."""
    ssid = html_mod.escape(hotspot_ssid)
    password = html_mod.escape(hotspot_password)
    networks_json = _script_json(networks)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>WrzDJ Kiosk Setup</title>
<style>
{SETUP_STYLES}
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
{SETUP_SCRIPT}
</script>
</body>
</html>"""
