"""Behavioural fakes for outbound HTTP in tests.

The suite blocks real network calls (conftest ``_block_outbound_http``). A test that needs a
provider registers fake responses on the ``fake_http`` fixture instead; the app's own request
building and response parsing still run, only the wire is replaced. Unregistered calls stay
blocked and fail the test.

    def test_x(fake_http):
        fake_http.add("GET", "https://api.example.com/v1/thing", json={"ok": True})
        fake_http.add("POST", "https://api.example.com/v1/rate", status=429,
                      headers={"Retry-After": "2"})
        fake_http.add("GET", "https://api.example.com/v1/slow", raises="timeout")
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Route:
    method: str
    url: str  # matched against the request URL without its query string; trailing "*" = prefix
    status: int = 200
    json: Any = None  # a value, or a callable(request_body_bytes) -> value
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    raises: str | None = None  # "timeout" or "connect"

    def matches(self, method: str, url: str) -> bool:
        if method.upper() != self.method:
            return False
        bare = url.split("?", 1)[0]
        if self.url.endswith("*"):
            return bare.startswith(self.url[:-1])
        return bare == self.url

    def payload(self, request_body: bytes | None) -> tuple[bytes, dict[str, str]]:
        headers = dict(self.headers)
        if self.json is not None:
            value = self.json(request_body or b"") if callable(self.json) else self.json
            headers.setdefault("Content-Type", "application/json")
            return _json.dumps(value).encode(), headers
        return self.body, headers


@dataclass
class FakeHttp:
    routes: list[Route] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def add(
        self,
        method: str,
        url: str,
        *,
        status: int = 200,
        json: Any | Callable[[bytes], Any] = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        raises: str | None = None,
    ) -> FakeHttp:
        # Newest first, so a test can override a provider default with a bad-day scenario.
        self.routes.insert(0, Route(method.upper(), url, status, json, body, headers or {}, raises))
        return self

    def find(self, method: str, url: str) -> Route | None:
        for route in self.routes:
            if route.matches(method, url):
                self.calls.append((method.upper(), url))
                return route
        return None

    def called(self, method: str, url_prefix: str) -> int:
        return sum(1 for m, u in self.calls if m == method.upper() and u.startswith(url_prefix))
