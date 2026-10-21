"""Read the allowlisted kiosk key-value configuration without executing it."""

import logging
import os
import secrets
from typing import TypedDict

from portal_defaults import (
    DEFAULT_HOTSPOT_SSID,
    DEFAULT_KIOSK_URL,
)

log = logging.getLogger("wifi-portal")

CONF_FILE = "/etc/wrzdj-kiosk.conf"


class ConfigReadError(RuntimeError):
    """Configuration could not be read; the original error is retained as cause."""


class PortalConfig(TypedDict):
    KIOSK_URL: str
    HOTSPOT_SSID: str
    HOTSPOT_PASSWORD: str


def load_config() -> PortalConfig:
    """Read the portal's settings; installer-only keys are ignored."""
    config: PortalConfig = {
        "KIOSK_URL": DEFAULT_KIOSK_URL,
        "HOTSPOT_SSID": DEFAULT_HOTSPOT_SSID,
        "HOTSPOT_PASSWORD": secrets.token_urlsafe(12),
    }
    if not os.path.isfile(CONF_FILE):
        log.warning("Config file %s not found, using defaults", CONF_FILE)
        return config
    try:
        with open(CONF_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"')
                if key == "KIOSK_URL":
                    config["KIOSK_URL"] = value
                elif key == "HOTSPOT_SSID":
                    config["HOTSPOT_SSID"] = value
                elif key == "HOTSPOT_PASSWORD" and value:
                    config["HOTSPOT_PASSWORD"] = value
    except (OSError, UnicodeError) as error:
        raise ConfigReadError(
            f"Unable to read kiosk configuration at {CONF_FILE}"
        ) from error
    return config
