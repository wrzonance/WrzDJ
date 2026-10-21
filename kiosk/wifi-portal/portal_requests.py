"""Validate untrusted WiFi setup requests before changing radio state."""

import json
import re

MAX_REQUEST_BYTES = 4096


def decode_connect_request(body: bytes) -> tuple[str, str]:
    """Return exact SSID/password values or a safe, user-facing validation error."""
    try:
        data = json.loads(body)
    except ValueError as error:
        raise ValueError("Invalid JSON") from error
    if not isinstance(data, dict):
        raise ValueError("Invalid request")
    ssid = data.get("ssid", "")
    password = data.get("password", "")
    if not isinstance(ssid, str) or not isinstance(password, str):
        raise ValueError("Invalid request")
    if not ssid:
        raise ValueError("SSID is required")
    if re.search(r"[\x00-\x1f\ud800-\udfff]", ssid) or re.search(
        r"[\x00-\x1f\ud800-\udfff]", password
    ):
        raise ValueError("Invalid characters in input")
    if len(ssid.encode("utf-8")) > 32 or len(password.encode("utf-8")) > 63:
        raise ValueError("SSID or password too long")
    return ssid, password
