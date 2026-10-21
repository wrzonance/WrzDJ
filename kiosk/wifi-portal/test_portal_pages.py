"""Presentation boundary regressions for the kiosk portal (baseline 57cfcdc6867f)."""

import subprocess
from html.parser import HTMLParser
from pathlib import Path

import portal_pages as pages


def test_rescan_client_reports_denial_failure_and_timeout():
    page = pages.html_setup(
        "Setup", "password123", [{"ssid": "Network", "signal": 80, "security": "Open"}]
    )
    run_portal_client(page)


def test_browser_client_script_extraction_accepts_uppercase_tags():
    page = pages.html_setup("Setup", "password123", [])
    uppercase_tags = page.replace("<script>", "<SCRIPT>").replace("</script>", "</SCRIPT>")
    run_portal_client(uppercase_tags)


def run_portal_client(page):
    # Parse repository-generated test HTML to execute its inline client script.
    parser = InlineScriptCollector()
    parser.feed(page)
    assert len(parser.scripts) == 1
    subprocess.run(
        ["node", str(Path(__file__).parents[1] / "tests/test_portal_client.cjs")],
        input=parser.script,
        text=True,
        check=True,
        timeout=10,
    )


class InlineScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self._current_script = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._current_script = []
            self.scripts.append(self._current_script)

    def handle_data(self, data):
        if self._current_script is not None:
            self._current_script.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self._current_script = None

    @property
    def script(self):
        return "".join(self.scripts[0])


def test_setup_accepts_only_the_settings_it_renders():
    page = pages.html_setup("Setup network", "password123", [])
    assert "Setup network" in page
    assert "password123" in page


def test_network_name_cannot_break_out_of_script():
    networks = [
        {
            "ssid": "</script><script>alert('ssid')</script>",
            "signal": 75,
            "security": "WPA2",
        }
    ]
    page = pages.html_setup("Setup", "password123", networks)
    parser = InlineScriptCollector()
    parser.feed(page)
    assert len(parser.scripts) == 1


def test_redirect_url_cannot_break_out_of_script():
    page = pages.html_redirect("https://example.com/</script><script>alert(1)</script>")
    parser = InlineScriptCollector()
    parser.feed(page)
    assert len(parser.scripts) == 1


class TestHtmlRedirect:
    def test_contains_redirect_script(self):
        html = pages.html_redirect("https://app.wrzdj.com/kiosk-pair")
        assert "window.location.replace(" in html
        # Verify URL appears JSON-encoded in the script tag (quoted)
        assert '"https://app.wrzdj.com/kiosk-pair"' in html

    def test_rejects_javascript_scheme(self):
        html = pages.html_redirect("javascript:alert(1)")
        # Should fall back to default URL
        assert pages.DEFAULT_KIOSK_URL in html
        assert "javascript:" not in html

    def test_rejects_ftp_scheme(self):
        html = pages.html_redirect("ftp://evil.com")
        assert pages.DEFAULT_KIOSK_URL in html
        assert "ftp:" not in html

    def test_allows_http(self):
        html = pages.html_redirect("http://192.168.1.5:3000/kiosk")
        # Verify URL appears JSON-encoded in the script tag (quoted)
        assert '"http://192.168.1.5:3000/kiosk"' in html

    def test_allows_https(self):
        html = pages.html_redirect("https://secure.example.com")
        # Verify URL appears JSON-encoded in the script tag (quoted)
        assert '"https://secure.example.com"' in html

    def test_json_encodes_url(self):
        # URL with special chars should be JSON-encoded for the JS
        html = pages.html_redirect('https://example.com/path?a=1&b="2"')
        # The JSON encoding should handle the quotes
        assert "window.location.replace(" in html

    def test_html_structure(self):
        html = pages.html_redirect("https://example.com")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Connecting to WrzDJ" in html


class TestHtmlSetup:
    def test_contains_network_list(self):
        networks = [
            {"ssid": "TestNet", "signal": 80, "security": "WPA2"},
            {"ssid": "OpenNet", "signal": 40, "security": "Open"},
        ]
        html = pages.html_setup("WrzDJ-Kiosk", "test", networks)
        assert "TestNet" in html
        assert "OpenNet" in html

    def test_html_escapes_config_values(self):
        config = {
            "HOTSPOT_SSID": '<script>alert("xss")</script>',
            "HOTSPOT_PASSWORD": "p&w<d>",
        }
        html = pages.html_setup(config["HOTSPOT_SSID"], config["HOTSPOT_PASSWORD"], [])
        assert '<script>alert("xss")</script>' not in html
        assert "&lt;script&gt;" in html
        assert "p&amp;w&lt;d&gt;" in html

    def test_json_serializes_networks(self):
        networks = [{"ssid": "Net'\"<>", "signal": 50, "security": "WPA2"}]
        html = pages.html_setup("Test", "pass", networks)
        # The JSON should be valid and embedded in the page
        assert "var networks =" in html

    def test_html_structure(self):
        html = pages.html_setup("Test", "pass", [])
        assert "<!DOCTYPE html>" in html
        assert "WrzDJ Kiosk Setup" in html
        assert "Connect" in html
