"""Tests for Cloudflare Turnstile CAPTCHA verification."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.turnstile import verify_turnstile_token


@pytest.mark.asyncio
class TestVerifyTurnstileToken:
    @patch("app.services.turnstile.get_settings")
    async def test_dev_mode_bypass_when_no_key(self, mock_settings):
        """In dev mode with no secret key, verification is skipped (returns True)."""
        settings = MagicMock()
        settings.turnstile_secret_key = ""
        settings.is_production = False
        mock_settings.return_value = settings

        result = await verify_turnstile_token("any-token", "1.2.3.4")
        assert result is True

    @patch("app.services.turnstile.get_settings")
    async def test_production_rejects_without_key(self, mock_settings):
        """In production with no secret key, verification fails (security default)."""
        settings = MagicMock()
        settings.turnstile_secret_key = ""
        settings.is_production = True
        mock_settings.return_value = settings

        result = await verify_turnstile_token("any-token", "1.2.3.4")
        assert result is False

    @patch("app.services.turnstile.httpx.AsyncClient")
    @patch("app.services.turnstile.get_settings")
    async def test_valid_token_returns_true(self, mock_settings, mock_client_cls):
        settings = MagicMock()
        settings.turnstile_secret_key = "test-secret"
        settings.is_production = True
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await verify_turnstile_token("valid-token", "1.2.3.4")
        assert result is True

        # Verify the correct data was posted
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["secret"] == "test-secret"
        assert call_kwargs[1]["data"]["response"] == "valid-token"
        assert call_kwargs[1]["data"]["remoteip"] == "1.2.3.4"

    @patch("app.services.turnstile.httpx.AsyncClient")
    @patch("app.services.turnstile.get_settings")
    async def test_invalid_token_returns_false(self, mock_settings, mock_client_cls):
        settings = MagicMock()
        settings.turnstile_secret_key = "test-secret"
        settings.is_production = True
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": False, "error-codes": ["invalid-input"]}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await verify_turnstile_token("invalid-token")
        assert result is False

    @pytest.mark.parametrize("payload", [None, [], "unexpected"])
    @patch("app.services.turnstile.httpx.AsyncClient")
    @patch("app.services.turnstile.get_settings")
    async def test_non_object_json_response_fails_closed(
        self, mock_settings, mock_client_cls, payload
    ):
        settings = MagicMock()
        settings.turnstile_secret_key = "test-secret"
        settings.is_production = True
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = payload
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        assert await verify_turnstile_token("token") is False

    @pytest.mark.parametrize("success", [1, "true"])
    @patch("app.services.turnstile.httpx.AsyncClient")
    @patch("app.services.turnstile.get_settings")
    async def test_success_flag_must_be_boolean_true(self, mock_settings, mock_client_cls, success):
        settings = MagicMock()
        settings.turnstile_secret_key = "test-secret"
        settings.is_production = True
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": success}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        assert await verify_turnstile_token("token") is False

    @patch("app.services.turnstile.httpx.AsyncClient")
    @patch("app.services.turnstile.get_settings")
    async def test_no_remoteip_omits_field(self, mock_settings, mock_client_cls):
        settings = MagicMock()
        settings.turnstile_secret_key = "test-secret"
        settings.is_production = False
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await verify_turnstile_token("token", None)

        call_kwargs = mock_client.post.call_args
        assert "remoteip" not in call_kwargs[1]["data"]
