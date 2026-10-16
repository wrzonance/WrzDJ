"""Apple Music developer-token configuration and endpoint tests."""

import logging
from unittest.mock import Mock

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
        apple_music_origins="https://music.example.com",
        cors_origins="https://unrelated.example.com",
    )


def test_developer_token_is_es256_and_short_lived(apple_settings):
    token, expires_at = apple_music.create_developer_token(apple_settings, now=1_800_000_000)

    assert jwt.get_unverified_header(token) == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "TEAM123456"
    assert claims["iat"] == 1_800_000_000
    assert expires_at == claims["exp"]
    assert claims["origin"] == ["https://music.example.com"]
    assert 0 < expires_at - claims["iat"] <= apple_music.DEVELOPER_TOKEN_TTL_SECONDS


def test_developer_token_rejects_malformed_private_key(apple_settings, caplog):
    secret_marker = "private-key-secret-marker"
    apple_settings.apple_music_private_key = secret_marker

    with caplog.at_level(logging.WARNING, logger=apple_music.__name__):
        with pytest.raises(apple_music.AppleMusicNotConfigured):
            apple_music.create_developer_token(apple_settings, now=1_800_000_000)

    assert "configured private key is invalid or unsupported" in caplog.text
    assert secret_marker not in caplog.text


def test_developer_token_rejects_invalid_apple_origin(apple_settings):
    apple_settings.apple_music_origins = "https://music.example.com/path"

    with pytest.raises(apple_music.AppleMusicNotConfigured):
        apple_music.create_developer_token(apple_settings, now=1_800_000_000)


def test_developer_token_requires_apple_credentials():
    with pytest.raises(apple_music.AppleMusicNotConfigured):
        apple_music.create_developer_token(
            Settings(
                apple_music_team_id="",
                apple_music_key_id="",
                apple_music_private_key="",
                apple_music_origins="",
            ),
            now=1_800_000_000,
        )


@pytest.mark.parametrize(
    ("music_user_token", "expected_error"),
    [
        (None, apple_music.AppleMusicNotConfigured),
        ("dj-user-token", apple_music.AppleMusicUserAuthorizationError),
    ],
)
def test_unauthorized_response_reports_the_credential_that_failed(
    monkeypatch, music_user_token, expected_error
):
    response = Mock(status_code=401)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setattr(apple_music.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(expected_error):
        apple_music.apple_get("/me/library", "developer-token", music_user_token=music_user_token)


def test_api_developer_token_reports_clear_not_configured(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.apple_music_tokens.get_settings",
        lambda: Settings(
            apple_music_team_id="",
            apple_music_key_id="",
            apple_music_private_key="",
            apple_music_origins="",
        ),
    )

    response = client.get("/api/apple-music/developer-token", headers=auth_headers)

    assert response.status_code == 503
    assert response.json()["detail"] == "Apple Music is not configured"


def test_api_developer_token_is_not_cached(client, auth_headers, monkeypatch, apple_settings):
    monkeypatch.setattr("app.services.apple_music_tokens.get_settings", lambda: apple_settings)

    response = client.get("/api/apple-music/developer-token", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["developer_token"]
