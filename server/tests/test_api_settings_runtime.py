"""Request handlers observe settings refreshed after API modules are imported."""

# Regression pinned to 57cfcdc6867f: importing route modules must not snapshot settings.

from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.api import auth, beatport, events, guest
from app.core.rate_limit import limiter


def test_auth_public_settings_reads_current_settings(monkeypatch, db):
    current = SimpleNamespace(turnstile_site_key="refreshed-site-key")
    monkeypatch.setattr(auth, "get_settings", lambda: current)
    monkeypatch.setattr(
        auth,
        "get_system_settings",
        lambda _db: SimpleNamespace(registration_enabled=True),
    )

    response = auth.get_public_settings(request=None, db=db)

    assert response.turnstile_site_key == "refreshed-site-key"


def test_event_public_url_reads_current_settings(monkeypatch):
    monkeypatch.setattr(
        events,
        "get_settings",
        lambda: SimpleNamespace(public_url="https://new.example.test/"),
    )

    assert events._get_base_url(None) == "https://new.example.test"


def test_guest_cookie_security_reads_current_settings(monkeypatch):
    from app.services.guests.identity import IdentifyResult

    monkeypatch.setattr(
        guest,
        "get_settings",
        lambda: SimpleNamespace(env="production"),
    )
    monkeypatch.setattr(
        guest,
        "identify_guest",
        lambda *_args, **_kwargs: IdentifyResult(
            guest_id="guest-id", action="create", reconcile_hint=None, token="guest-token"
        ),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/guest/identify",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
        }
    )

    response = guest.identify(
        payload=SimpleNamespace(fingerprint_hash="hash", fingerprint_components={}),
        request=request,
        db=None,
    )

    assert "secure" in response.headers["set-cookie"].lower()


def test_beatport_status_configuration_reads_current_settings(monkeypatch, db):
    monkeypatch.setattr(
        beatport,
        "get_settings",
        lambda: SimpleNamespace(beatport_client_id="refreshed-client-id"),
    )
    monkeypatch.setattr(
        beatport,
        "get_system_settings",
        lambda _db: SimpleNamespace(beatport_enabled=True),
    )

    response = beatport.get_status(
        current_user=SimpleNamespace(
            beatport_access_token=None,
            beatport_token_expires_at=None,
            beatport_subscription=None,
        ),
        db=db,
    )

    assert response.configured is True


@pytest.mark.parametrize(
    ("route", "module_name", "setting_name"),
    [
        ("app.api.auth.login", "app.api.auth", "login_rate_limit_per_minute"),
        ("app.api.auth.register", "app.api.auth", "registration_rate_limit_per_minute"),
        ("app.api.events.event_search", "app.api.events", "search_rate_limit_per_minute"),
        (
            "app.api.events_requests.submit_request",
            "app.api.events_requests",
            "request_rate_limit_per_minute",
        ),
        ("app.api.beatport.search", "app.api.beatport", "search_rate_limit_per_minute"),
        ("app.api.tidal.search", "app.api.tidal", "search_rate_limit_per_minute"),
    ],
)
def test_rate_limit_reads_current_settings_after_import(
    monkeypatch, route, module_name, setting_name
):
    module = import_module(module_name)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(**{setting_name: 7}),
    )

    dynamic_limit = limiter._dynamic_route_limits[route][0]
    parsed_limit = next(iter(dynamic_limit)).limit

    assert parsed_limit.amount == 7


@pytest.mark.parametrize(
    ("path", "service", "message"),
    [
        (
            "/api/apple-music/disconnect",
            "app.api.apple_music.apple_music_accounts",
            "Apple Music account disconnected",
        ),
        ("/api/spotify/disconnect", "app.api.spotify.disconnect", "Spotify account disconnected"),
        ("/api/tidal/disconnect", "app.api.tidal.disconnect_tidal", "Tidal account disconnected"),
        (
            "/api/beatport/disconnect",
            "app.api.beatport.disconnect_beatport",
            "Beatport account disconnected",
        ),
    ],
)
def test_provider_disconnect_responses_share_status_message_contract(
    client, auth_headers, monkeypatch, path, service, message
):
    """Provider disconnect response models stay consistent without changing success status."""
    if service.endswith("apple_music_accounts"):
        monkeypatch.setattr(
            "app.api.apple_music.apple_music_accounts.disconnect_account", lambda *_args: None
        )
    else:
        monkeypatch.setattr(service, lambda *_args: None)

    response = client.post(path, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": message}
