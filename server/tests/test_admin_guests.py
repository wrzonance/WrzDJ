"""Tests for the admin Guests endpoints and helpers (#862)."""

from app.services.admin_guests import mask_email
from app.services.guest_identity import browser_label

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


class TestHelpers:
    def test_mask_email_keeps_first_char_and_domain(self):
        assert mask_email("alice@example.com") == "a***@example.com"
        assert mask_email("a@b.co") == "a***@b.co"

    def test_browser_label_known_ua(self):
        assert browser_label(IPHONE_UA) == "Safari · iOS"

    def test_browser_label_unknown_or_missing(self):
        assert browser_label("curl/8.0") is None
        assert browser_label(None) is None
