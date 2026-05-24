"""Tests for the OpenAI-compatible base URL validator."""

import pytest

from app.services.llm.url_validator import (
    InvalidBaseUrlError,
    validate_compatible_base_url,
)


class TestValidateCompatibleBaseUrl:
    def test_https_any_host_accepted(self):
        assert validate_compatible_base_url("https://api.openai.com/v1") == (
            "https://api.openai.com/v1"
        )

    def test_https_strips_trailing_slash(self):
        assert validate_compatible_base_url("https://example.com/v1/") == ("https://example.com/v1")

    def test_http_loopback_localhost_ok(self):
        assert validate_compatible_base_url("http://localhost:8080") == "http://localhost:8080"

    def test_http_loopback_ip_ok(self):
        assert validate_compatible_base_url("http://127.0.0.1:8000") == ("http://127.0.0.1:8000")

    def test_http_rfc1918_192_ok(self):
        assert validate_compatible_base_url("http://192.168.1.100") == ("http://192.168.1.100")

    def test_http_rfc1918_10_ok(self):
        assert validate_compatible_base_url("http://10.0.0.5/v1") == ("http://10.0.0.5/v1")

    def test_http_rfc1918_172_ok(self):
        assert validate_compatible_base_url("http://172.20.0.1") == "http://172.20.0.1"

    def test_http_public_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("http://example.com/v1")

    def test_http_with_8_8_8_8_rejected(self):
        # public IP — must require HTTPS
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("http://8.8.8.8")

    def test_embedded_credentials_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("https://user:pass@example.com/v1")

    def test_query_string_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("https://example.com/v1?api_key=secret")

    def test_fragment_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("https://example.com/v1#fragment")

    def test_empty_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("")

    def test_missing_scheme_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("example.com/v1")

    def test_invalid_scheme_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("ftp://example.com")

    def test_missing_host_rejected(self):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url("https://")

    def test_https_root_no_path_ok(self):
        # Some servers accept the host root with no path
        assert validate_compatible_base_url("https://example.com") == ("https://example.com")

    def test_strips_trailing_slash_only(self):
        # Empty path becomes "" (no slash) per RFC
        assert validate_compatible_base_url("https://example.com/") == ("https://example.com")

    def test_preserves_port(self):
        assert validate_compatible_base_url("http://127.0.0.1:11434/v1") == (
            "http://127.0.0.1:11434/v1"
        )
