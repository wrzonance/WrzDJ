"""Tests for the OpenAI-compatible base URL validator."""

import pytest

from app.services.llm.url_validator import (
    InvalidBaseUrlError,
    validate_compatible_base_url,
)


class TestValidateCompatibleBaseUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://api.openai.com/v1", "https://api.openai.com/v1"),
            ("https://example.com/v1/", "https://example.com/v1"),  # strips trailing slash
            ("http://localhost:8080", "http://localhost:8080"),  # loopback hostname
            ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),  # loopback IP
            ("http://192.168.1.100", "http://192.168.1.100"),  # RFC1918 192.168/16
            ("http://10.0.0.5/v1", "http://10.0.0.5/v1"),  # RFC1918 10/8
            ("http://172.20.0.1", "http://172.20.0.1"),  # RFC1918 172.16/12
            ("https://example.com", "https://example.com"),  # host root, no path
            ("https://example.com/", "https://example.com"),  # empty path → no slash
            ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1"),  # preserves port
            ("http://[::1]:8080", "http://[::1]:8080"),  # IPv6 loopback
            ("http://[fc00::1]/v1", "http://[fc00::1]/v1"),  # IPv6 unique-local fc00::/7
            ("http://[fe80::1]", "http://[fe80::1]"),  # IPv6 link-local fe80::/10
            (
                "https://example.com/v1/chat/completions",
                "https://example.com/v1/chat/completions",
            ),  # multi-segment path preserved
        ],
    )
    def test_accepts_and_normalises(self, url, expected):
        assert validate_compatible_base_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/v1",  # public host must use HTTPS
            "http://8.8.8.8",  # public IP must use HTTPS
            "https://user:pass@example.com/v1",  # embedded credentials
            "https://example.com/v1?api_key=secret",  # query string
            "https://example.com/v1#fragment",  # fragment
            "",  # empty
            "example.com/v1",  # missing scheme
            "ftp://example.com",  # invalid scheme
            "https://",  # missing host
            "http://[2001:4860:4860::8888]",  # public IPv6 (Google DNS)
            "   ",  # whitespace only
        ],
    )
    def test_rejects(self, url):
        with pytest.raises(InvalidBaseUrlError):
            validate_compatible_base_url(url)

    def test_case_normalization_scheme(self):
        # Scheme is lower-cased; netloc and path are preserved as-given.
        result = validate_compatible_base_url("HTTPS://EXAMPLE.COM/V1")
        assert result.startswith("https://")
        assert result.endswith("/V1")
