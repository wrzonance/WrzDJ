"""Tests for template playlist API endpoints.

Tests cover:
- GET /{code}/playlists — list user playlists
- POST /{code}/recommendations/from-template — generate from template
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.services.recommendation.scorer import EventProfile, ScoredTrack
from app.services.recommendation.service import RecommendationResult
from app.services.tracks.profile import TrackProfile


@pytest.fixture
def user_with_tidal(db: Session, test_user: User) -> User:
    """Give the test user Tidal credentials."""
    test_user.tidal_access_token = "fake_tidal_token"
    test_user.tidal_refresh_token = "fake_tidal_refresh"
    db.commit()
    db.refresh(test_user)
    return test_user


@pytest.fixture
def user_with_beatport(db: Session, test_user: User) -> User:
    """Give the test user Beatport credentials."""
    test_user.beatport_access_token = "fake_bp_token"
    test_user.beatport_refresh_token = "fake_bp_refresh"
    test_user.beatport_token_expires_at = utcnow() + timedelta(hours=1)
    db.commit()
    db.refresh(test_user)
    return test_user


def _mock_playlists_response():
    """Mock playlist info objects for patching."""
    from app.services.providers.beatport import BeatportPlaylistInfo
    from app.services.providers.tidal import TidalPlaylistInfo

    return {
        "tidal": [
            TidalPlaylistInfo(
                id="tidal-1",
                name="Tidal Mix",
                num_tracks=10,
                description="Tidal playlist",
                cover_url="https://img.tidal.com/1.jpg",
            )
        ],
        "beatport": [
            BeatportPlaylistInfo(
                id="bp-1",
                name="Beatport Mix",
                num_tracks=20,
                description="Beatport playlist",
                cover_url="https://bp.com/1.jpg",
            )
        ],
    }


def _mock_template_result():
    """Create a mock RecommendationResult for template recommendations."""
    return RecommendationResult(
        suggestions=[
            ScoredTrack(
                profile=TrackProfile(
                    title="Template Suggestion",
                    artist="Template DJ",
                    bpm=126.0,
                    key="7A",
                    genre="Progressive House",
                    source="beatport",
                    track_id="t-123",
                    url="https://beatport.com/track/test/t-123",
                    cover_url="https://bp.com/cover.jpg",
                    duration_seconds=400,
                ),
                score=0.88,
                bpm_score=0.9,
                key_score=1.0,
                genre_score=0.7,
            ),
        ],
        event_profile=EventProfile(
            avg_bpm=126.0,
            bpm_range=(122.0, 130.0),
            dominant_keys=["7A"],
            dominant_genres=["Progressive House"],
            track_count=15,
        ),
        enriched_count=15,
        total_candidates_searched=30,
        services_used=["beatport"],
    )


# ============================================================
# GET /{code}/playlists
# ============================================================


class TestGetPlaylists:
    @patch("app.services.providers.beatport.list_user_playlists")
    @patch("app.services.providers.tidal.list_user_playlists")
    def test_200_with_playlists_from_both_services(
        self,
        mock_tidal_playlists,
        mock_bp_playlists,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        user_with_tidal: User,
        user_with_beatport: User,
    ):
        mocks = _mock_playlists_response()
        mock_tidal_playlists.return_value = mocks["tidal"]
        mock_bp_playlists.return_value = mocks["beatport"]

        response = client.get(
            f"/api/events/{test_event.code}/playlists",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "playlists" in data
        assert len(data["playlists"]) == 2
        sources = {p["source"] for p in data["playlists"]}
        assert sources == {"tidal", "beatport"}

    def test_200_empty_list_no_services(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
    ):
        response = client.get(
            f"/api/events/{test_event.code}/playlists",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["playlists"] == []

    def test_401_without_auth(self, client: TestClient, test_event: Event):
        response = client.get(f"/api/events/{test_event.code}/playlists")
        assert response.status_code == 401

    def test_404_for_non_owner(self, client: TestClient, db: Session, test_event: Event):
        from app.services.auth import get_password_hash

        other_user = User(
            username="otheruser2",
            password_hash=get_password_hash("otherpassword123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        login_resp = client.post(
            "/api/auth/login",
            data={"username": "otheruser2", "password": "otherpassword123"},
        )
        other_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        response = client.get(
            f"/api/events/{test_event.code}/playlists",
            headers=other_headers,
        )
        assert response.status_code == 404


# ============================================================
# POST /{code}/recommendations/from-template
# ============================================================


class TestFromTemplate:
    @patch("app.services.recommendation.service.generate_recommendations_from_template")
    def test_200_with_valid_template(
        self,
        mock_generate,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        user_with_beatport: User,
    ):
        mock_generate.return_value = _mock_template_result()

        response = client.post(
            f"/api/events/{test_event.code}/recommendations/from-template",
            headers=auth_headers,
            json={"source": "beatport", "playlist_id": "bp-playlist-1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["title"] == "Template Suggestion"
        assert data["profile"]["avg_bpm"] == 126.0
        assert data["services_used"] == ["beatport"]

    def test_400_invalid_source(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        user_with_beatport: User,
    ):
        response = client.post(
            f"/api/events/{test_event.code}/recommendations/from-template",
            headers=auth_headers,
            json={"source": "spotify", "playlist_id": "some-id"},
        )
        assert response.status_code == 422  # pydantic validation

    def test_503_no_services_connected(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
    ):
        response = client.post(
            f"/api/events/{test_event.code}/recommendations/from-template",
            headers=auth_headers,
            json={"source": "tidal", "playlist_id": "some-id"},
        )
        assert response.status_code == 503

    def test_401_without_auth(self, client: TestClient, test_event: Event):
        response = client.post(
            f"/api/events/{test_event.code}/recommendations/from-template",
            json={"source": "tidal", "playlist_id": "some-id"},
        )
        assert response.status_code == 401

    def test_404_nonexistent_event(self, client: TestClient, auth_headers: dict):
        response = client.post(
            "/api/events/NONEXIST/recommendations/from-template",
            headers=auth_headers,
            json={"source": "tidal", "playlist_id": "some-id"},
        )
        assert response.status_code == 404

    @patch("app.services.recommendation.service.generate_recommendations_from_template")
    def test_response_schema_matches_recommendation_response(
        self,
        mock_generate,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        user_with_tidal: User,
    ):
        mock_generate.return_value = _mock_template_result()

        response = client.post(
            f"/api/events/{test_event.code}/recommendations/from-template",
            headers=auth_headers,
            json={"source": "tidal", "playlist_id": "tidal-playlist-1"},
        )
        data = response.json()

        # Same schema as regular recommendations
        assert "suggestions" in data
        assert "profile" in data
        assert "services_used" in data
        assert "total_candidates_searched" in data
        assert "llm_available" in data

        # Profile fields
        profile = data["profile"]
        assert "avg_bpm" in profile
        assert "dominant_keys" in profile
        assert "dominant_genres" in profile
        assert "track_count" in profile
