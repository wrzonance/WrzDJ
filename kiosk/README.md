# WrzDJ Kiosk — Raspberry Pi Setup

Turn a Raspberry Pi into a dedicated WrzDJ event display. The Pi boots straight into a locked-down browser showing the kiosk pairing screen — no desktop, no taskbar, no escape routes.

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Raspberry Pi | Pi 4 (2GB) | Pi 5 (4GB) |
| Storage | 8GB microSD | 16GB+ A2-rated microSD |
| Display | Any HDMI monitor | Official 7" touchscreen |
| Power | 5V 3A USB-C | Official Pi power supply |

A touchscreen is not required — guests can still submit requests from their phones. The kiosk display is view-only.

## Quick Start

### 1. Flash Raspberry Pi OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash **Raspberry Pi OS Lite (64-bit)** to your SD card.

Use Bookworm or newer with NetworkManager active. Setup checks this requirement
before making changes; the captive portal does not support legacy wpa_supplicant-only systems.

In Imager's settings (gear icon), configure:
- **Hostname**: `wrzdj-kiosk`
- **Enable SSH**: Yes (password authentication)
- **Username/password**: `pi` / your choice
- **WiFi**: Your venue's network

### 2. Boot and Connect

Insert the SD card, connect the display, power on the Pi. Wait ~60 seconds for first boot, then SSH in:

```
ssh pi@wrzdj-kiosk.local
```

### 3. Run Setup

```
git clone https://github.com/thewrz/WrzDJ
sudo ./WrzDJ/kiosk/setup.sh
```

The script installs everything and prompts you to reboot.

### 4. Pair the Kiosk

After reboot, the Pi shows a QR code on the kiosk pairing screen. From your phone:

1. Scan the QR code (or visit the URL shown)
2. Log in with your DJ account
3. Select which event to display
4. The kiosk redirects to the event display automatically

### 5. Done

The kiosk now shows the live event queue — now playing, accepted requests, recently played. It auto-recovers from crashes and power loss.

## WiFi Captive Portal

The kiosk includes a built-in WiFi captive portal. If the Pi boots without an internet connection (no WiFi pre-configured), the portal automatically:

1. Scans for available WiFi networks
2. Creates a `WrzDJ-Kiosk` hotspot (use the password shown on the kiosk screen)
3. Shows a WiFi setup page on the touchscreen
4. Opens the same setup page on any phone that connects to the hotspot

**From the touchscreen or your phone:** select a network, enter the password, and tap Connect. The kiosk redirects to the pairing screen automatically.

If WiFi was already configured (via Raspberry Pi Imager or a previous setup), the portal detects the connection and redirects immediately — you never see the setup page.

### Changing Hotspot Settings

Edit `/etc/wrzdj-kiosk.conf`:

```
HOTSPOT_SSID=MyCustomSSID
HOTSPOT_PASSWORD=mypassword
```

Restart the portal to reload those settings and restart the tty1 login session to reload Chromium:

```
sudo systemctl restart wrzdj-wifi-portal getty@tty1
```

### How It Works

The portal (`wrzdj-wifi-portal.service`) runs on port 80 after NetworkManager starts. The tty1 launcher waits for it before opening Chromium at `http://localhost`:

- **Internet available**: Portal serves a JS redirect to the kiosk pairing URL
- **No internet**: Portal starts a hotspot and serves the WiFi setup page

When a phone connects to the hotspot, all DNS resolves to the portal IP (`10.42.0.1`). The phone's OS detects this as a captive portal and pops up its built-in browser with the setup page.

## Configuration

Edit `/etc/wrzdj-kiosk.conf`, reload the portal settings, and restart the kiosk login session:

```
sudo nano /etc/wrzdj-kiosk.conf
sudo systemctl restart wrzdj-wifi-portal getty@tty1
```

| Variable | Default | Description |
|----------|---------|-------------|
| `KIOSK_URL` | `https://app.wrzdj.com/kiosk-pair` | Destination the portal opens when internet is available |
| `KIOSK_ROTATION` | `0` | Screen rotation: `0`, `90`, `180`, `270` |
| `EXTRA_CHROMIUM_FLAGS` | (empty) | Additional Chromium flags |
| `HOTSPOT_SSID` | `WrzDJ-Kiosk` | WiFi hotspot name for captive portal |
| `HOTSPOT_PASSWORD` | Generated during setup | WiFi hotspot password, displayed on the kiosk screen |

WiFi variables (`WIFI_SSID`, `WIFI_PASSWORD`, `WIFI_COUNTRY`) are only used during initial setup.

The portal reads `KIOSK_URL` and hotspot settings when it starts. Restart both `wrzdj-wifi-portal`
and `getty@tty1` to reload those values in the portal and Chromium. Changes to
`EXTRA_CHROMIUM_FLAGS` need a `getty@tty1` restart. To apply a rotation change, rerun `setup.sh`
and reboot so the firmware configuration takes effect.

## Self-Hosted Instances

If you run your own WrzDJ server, change the URL before running setup:

```
# Edit the config file
nano WrzDJ/kiosk/wrzdj-kiosk.conf
# Change KIOSK_URL to your server
# Then run setup
sudo ./WrzDJ/kiosk/setup.sh
```

Or edit after setup:

```
sudo sed -i 's|KIOSK_URL=.*|KIOSK_URL=https://your-server.com/kiosk-pair|' /etc/wrzdj-kiosk.conf
sudo systemctl restart wrzdj-wifi-portal getty@tty1
```

## SD Card Protection (Optional)

Hard power-offs (unplugging the Pi) can corrupt the SD card over time. OverlayFS makes the filesystem read-only — all writes go to RAM and are lost on reboot.

```
sudo ./WrzDJ/kiosk/overlayfs/setup-overlayfs.sh enable
sudo reboot
```

**Trade-off**: The kiosk session token (stored in Chromium's localStorage) is lost on every reboot, so the kiosk will re-enter pairing mode. Re-pairing takes about 30 seconds.

To make config changes with overlayfs enabled, temporarily disable it:

```
sudo ./WrzDJ/kiosk/overlayfs/setup-overlayfs.sh disable
sudo reboot
# Make changes...
sudo ./WrzDJ/kiosk/overlayfs/setup-overlayfs.sh enable
sudo reboot
```

Check current status:

```
sudo ./WrzDJ/kiosk/overlayfs/setup-overlayfs.sh status
```

## Troubleshooting

### No WiFi connection

If the captive portal didn't work, SSH in via Ethernet and check:
```
nmcli device status
nmcli device wifi list
nmcli device wifi connect "YourSSID" password "YourPassword"
```

Check the portal service status:
```
sudo systemctl status wrzdj-wifi-portal
sudo journalctl -u wrzdj-wifi-portal -n 50
```

### Black screen after setup

The display runs inside the kiosk user's tty1 login session. Check the getty and kiosk-user logs:
```
sudo systemctl status getty@tty1
sudo journalctl -u getty@tty1 --no-pager -n 100
sudo journalctl _UID="$(id -u kiosk)" --no-pager -n 100
```

Common fixes:
- GPU driver issue: Add `WLR_RENDERER=pixman` to `/etc/wrzdj-kiosk.conf`, then restart `getty@tty1`.
- Missing display: Check HDMI cable, try the other HDMI port on Pi 4/5

### Touch input not working

Verify the kiosk user has the right groups:
```
groups kiosk
# Should include: input video render
```

If the touchscreen needs calibration or a specific driver, install it before running setup.

### Screen rotation wrong

Edit `/etc/wrzdj-kiosk.conf`, set `KIOSK_ROTATION` to `0`, `90`, `180`, or `270`, then:
```
sudo ./WrzDJ/kiosk/setup.sh  # Re-run to apply rotation to config.txt
sudo reboot
```

### Chromium "restore pages" dialog

The watchdog timer should prevent this. If it appears, the watchdog may not be running:
```
sudo systemctl status wrzdj-kiosk-watchdog.timer
sudo systemctl enable --now wrzdj-kiosk-watchdog.timer
```

### Kiosk browser does not launch

The kiosk browser is started by the kiosk user's `.bash_profile` on tty1, not by a systemd display
service. Check the login session and confirm the portal is ready:
```
sudo systemctl status getty@tty1 wrzdj-wifi-portal
sudo journalctl -u getty@tty1 --no-pager -n 100
```

Common causes:
- Portal not running: Ensure `wrzdj-wifi-portal.service` is active (`sudo systemctl status wrzdj-wifi-portal`)
- Out of memory: Use a Pi with 2GB+ RAM

## Architecture

```
kiosk/
  setup.sh                          # Main setup script
  lib/
    setup-config.sh                 # Read, validate, and write kiosk configuration
    setup-platform.sh               # Configure packages, WiFi, user, rotation, and host
    setup-runtime.sh                # Install portal/watchdog units and tty1 launcher
  wrzdj-kiosk.conf                  # Default configuration template
  wifi-portal/
    portal.py                       # HTTP handlers, coordinated radio operations, startup
    portal_config.py                # Typed portal settings and generated fallback credentials
    portal_network.py               # NetworkManager commands and connectivity probes
    portal_requests.py              # WiFi request validation before radio changes
    portal_state.py                 # Server-owned cache, configuration and radio locks
    portal_pages.py                 # Safe HTML rendering, styles and browser script
    portal_defaults.py              # Default URL and hotspot name
    portal_types.py                 # Network and connection status payloads
    dnsmasq-captive.conf            # DNS redirect config for hotspot mode
  systemd/
    wrzdj-wifi-portal.service       # WiFi portal service (starts on boot)
    wrzdj-kiosk-watchdog.service    # Crash recovery (oneshot)
    wrzdj-kiosk-watchdog.timer      # Fires watchdog every 30s
    wrzdj-kiosk-watchdog.sh         # Clears Chromium crash flags
  overlayfs/
    setup-overlayfs.sh              # SD card write protection (optional)
```

The kiosk runs [Cage](https://github.com/cage-kiosk/cage), a minimal Wayland compositor that locks the display to a single fullscreen application — Chromium in kiosk mode. There is no desktop environment, no window manager, no way for users to escape to a shell.

Cage requires logind seat access (DRM/input devices), so it launches from the kiosk user's `.bash_profile` on tty1 auto-login — not from a systemd service. When Cage exits, the login session ends, getty restarts auto-login, and `.bash_profile` re-launches Cage (self-healing).

On boot, the WiFi portal (`wrzdj-wifi-portal.service`) starts on port 80 after NetworkManager. The kiosk user auto-logs in on tty1, `.bash_profile` waits for the portal to be ready, then launches Cage + Chromium pointing at `http://localhost`. If internet is available, the portal redirects to the kiosk pairing URL. If not, it shows a WiFi setup page and creates a hotspot for phone-based configuration.
