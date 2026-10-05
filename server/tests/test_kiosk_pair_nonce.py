"""Tests for kiosk-pair nonce mechanism."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


class TestPairChallenge:
    def test_returns_nonce_with_expiry(self, client: TestClient):
        response = client.get("/api/public/kiosk/pair-challenge")
        assert response.status_code == 200
        body = response.json()
        assert "nonce" in body
        assert isinstance(body["nonce"], str)
        # secrets.token_urlsafe(16) → ~22-char base64url string
        assert len(body["nonce"]) >= 16
        assert body["expires_in"] == 10

    def test_pair_with_valid_nonce_succeeds(self, client: TestClient):
        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        response = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert response.status_code == 200
        assert "pair_code" in response.json()

    def test_pair_without_nonce_400(self, client: TestClient):
        response = client.post("/api/public/kiosk/pair")
        assert response.status_code == 400
        assert "nonce" in response.json()["detail"].lower()

    def test_pair_with_invalid_nonce_400(self, client: TestClient):
        client.get("/api/public/kiosk/pair-challenge")  # Issue one for this IP
        response = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": "totally-wrong-nonce-value-here"},
        )
        assert response.status_code == 400

    def test_nonce_single_use(self, client: TestClient):
        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        # First use succeeds
        first = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert first.status_code == 200
        # Second use with same nonce fails (consumed)
        second = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert second.status_code == 400

    def test_nonce_expires_after_10s(self, client: TestClient, monkeypatch):
        """Mock time so we don't actually wait 10s."""
        from app.api import kiosk

        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        # Fast-forward time
        real_time = time.time
        monkeypatch.setattr(kiosk.time, "time", lambda: real_time() + 11)
        response = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()


class TestPairChallengeIndependence:
    """Issue #713: concurrent challenges from one IP stay independent."""

    def test_second_challenge_from_same_ip_keeps_first_valid(self, client: TestClient):
        first = client.get("/api/public/kiosk/pair-challenge").json()
        second = client.get("/api/public/kiosk/pair-challenge").json()
        response = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": first["nonce"]},
        )
        assert response.status_code == 200
        response = client.post("/api/public/kiosk/pair", headers={"X-Pair-Nonce": second["nonce"]})
        assert response.status_code == 200

    @pytest.mark.parametrize("headers", [{}, {"X-Pair-Nonce": "totally-wrong-nonce-value-here"}])
    def test_invalid_attempt_does_not_consume_valid_challenge(self, client: TestClient, headers):
        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        bad = client.post(
            "/api/public/kiosk/pair",
            headers=headers,
        )
        assert bad.status_code == 400
        good = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert good.status_code == 200

    def test_nonce_rejected_from_a_different_ip(self, client: TestClient, monkeypatch):
        from app.api import kiosk

        monkeypatch.setattr(kiosk, "get_client_ip", lambda request: "203.0.113.1")
        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        monkeypatch.setattr(kiosk, "get_client_ip", lambda request: "203.0.113.2")
        response = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert response.status_code == 400
        monkeypatch.setattr(kiosk, "get_client_ip", lambda request: "203.0.113.1")
        response = client.post(
            "/api/public/kiosk/pair", headers={"X-Pair-Nonce": challenge["nonce"]}
        )
        assert response.status_code == 200

    def test_expired_nonce_does_not_consume_younger_challenge(self, client, monkeypatch):
        from app.api import kiosk

        now = time.time()
        monkeypatch.setattr(kiosk.time, "time", lambda: now)
        expired = client.get("/api/public/kiosk/pair-challenge").json()
        now += 6
        valid = client.get("/api/public/kiosk/pair-challenge").json()
        now += 5
        rejected = client.post("/api/public/kiosk/pair", headers={"X-Pair-Nonce": expired["nonce"]})
        assert rejected.status_code == 400
        assert "expired" in rejected.json()["detail"].lower()
        accepted = client.post("/api/public/kiosk/pair", headers={"X-Pair-Nonce": valid["nonce"]})
        assert accepted.status_code == 200

    def test_simultaneous_replay_creates_only_one_pairing(self, client, monkeypatch):
        """Regression for df1b9790: lookup/check/pop allowed concurrent reuse."""
        from app.api import kiosk
        from app.core.time import utcnow

        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        first_comparing = Event()
        second_comparing = Event()
        real_compare = kiosk.hmac.compare_digest

        def overlapping_compare(left, right):
            if not first_comparing.is_set():
                first_comparing.set()
                # Old code lets the second request enter validation here. With
                # atomic consumption it waits, then rejects the consumed nonce.
                second_comparing.wait(timeout=2)
            else:
                second_comparing.set()
            return real_compare(left, right)

        create = Mock(
            return_value=SimpleNamespace(
                pair_code="ABC234", session_token="test-session", pair_expires_at=utcnow()
            )
        )
        monkeypatch.setattr(kiosk.hmac, "compare_digest", overlapping_compare)
        monkeypatch.setattr(kiosk, "create_kiosk", create)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                client.post, "/api/public/kiosk/pair", headers={"X-Pair-Nonce": challenge["nonce"]}
            )
            assert first_comparing.wait(timeout=5), "First request never reached validation"
            second = pool.submit(
                client.post, "/api/public/kiosk/pair", headers={"X-Pair-Nonce": challenge["nonce"]}
            )
            responses = [first.result(timeout=5), second.result(timeout=5)]
        assert sorted(response.status_code for response in responses) == [200, 400]
        create.assert_called_once()
