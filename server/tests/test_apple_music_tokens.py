"""Apple Music developer-token configuration and endpoint tests."""

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import Settings
from app.services import apple_music_tokens as apple_music


@pytest.fixture
def apple_settings():
    private_key = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    return Settings(
        apple_music_team_id="TEAM123456",
        apple_music_key_id="KEY1234567",
        apple_music_private_key=private_key,
    )


def test_developer_token_is_es256_and_short_lived(apple_settings):
    token, expires_at = apple_music.create_developer_token(apple_settings, now=1_800_000_000)

    assert jwt.get_unverified_header(token) == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "TEAM123456"
    assert claims["iat"] == 1_800_000_000
    assert expires_at == claims["exp"]
    assert 0 < expires_at - claims["iat"] <= apple_music.DEVELOPER_TOKEN_TTL_SECONDS


def test_developer_token_rejects_malformed_private_key(apple_settings):
    apple_settings.apple_music_private_key = "not a private key"

    with pytest.raises(apple_music.AppleMusicNotConfigured):
        apple_music.create_developer_token(apple_settings, now=1_800_000_000)


def test_developer_token_requires_apple_credentials():
    with pytest.raises(apple_music.AppleMusicNotConfigured):
        apple_music.create_developer_token(Settings(), now=1_800_000_000)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, {"data": []}, apple_music.AppleMusicRequestUncertain),
        (200, ValueError("invalid json"), apple_music.AppleMusicRequestUncertain),
        (401, {"errors": []}, apple_music.AppleMusicNotConfigured),
        (403, {"errors": []}, apple_music.AppleMusicUserAuthorizationError),
        (400, {"errors": []}, apple_music.AppleMusicError),
    ],
)
def test_playlist_post_distinguishes_uncertain_writes_from_definite_rejections(
    monkeypatch, status, body, expected
):
    class Response:
        status_code = status
        is_success = 200 <= status < 300

        def raise_for_status(self):
            if status >= 400:
                request = httpx.Request(
                    "POST", "https://api.music.apple.com/v1/me/library/playlists"
                )
                response = httpx.Response(status, request=request)
                raise httpx.HTTPStatusError(
                    "Apple rejected the request", request=request, response=response
                )

        def json(self):
            if isinstance(body, Exception):
                raise body
            return body

    class Client:
        def __init__(self, *, timeout):
            assert timeout == apple_music.HTTP_TIMEOUT_SECONDS

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(apple_music.httpx, "Client", Client)
    with pytest.raises(expected):
        apple_music.apple_post(
            "/me/library/playlists",
            "developer-token",
            music_user_token="music-user-token",
            json_body={"attributes": {"name": "Set"}},
        )


def test_api_developer_token_reports_clear_not_configured(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.apple_music_tokens.get_settings", lambda: Settings())

    response = client.get("/api/apple-music/developer-token", headers=auth_headers)

    assert response.status_code == 503
    assert response.json()["detail"] == "Apple Music is not configured"


def test_api_developer_token_is_not_cached(client, auth_headers, monkeypatch, apple_settings):
    monkeypatch.setattr("app.services.apple_music_tokens.get_settings", lambda: apple_settings)

    response = client.get("/api/apple-music/developer-token", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["developer_token"]
