"""Tests for the recommendations API endpoint."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.recommendation.scorer import EventProfile, ScoredTrack, TrackProfile
from app.services.recommendation.service import RecommendationResult


@pytest.fixture
def event_with_requests(db: Session, test_user: User, test_event: Event) -> Event:
    """Create an event with some accepted requests."""
    for i in range(3):
        req = Request(
            event_id=test_event.id,
            song_title=f"Song {i}",
            artist=f"Artist {i}",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key=f"dedupe_{i}_{'x' * 20}",
        )
        db.add(req)
    db.commit()
    return test_event


@pytest.fixture
def user_with_beatport(db: Session, test_user: User) -> User:
    """Give the test user Beatport credentials."""
    test_user.beatport_access_token = "fake_token"
    test_user.beatport_refresh_token = "fake_refresh"
    test_user.beatport_token_expires_at = utcnow() + timedelta(hours=1)
    db.commit()
    db.refresh(test_user)
    return test_user


def _mock_recommendation_result():
    """Create a mock RecommendationResult for patching."""
    return RecommendationResult(
        suggestions=[
            ScoredTrack(
                profile=TrackProfile(
                    title="Suggested Track",
                    artist="Cool DJ",
                    bpm=128.0,
                    key="8A",
                    genre="Tech House",
                    source="beatport",
                    track_id="12345",
                    url="https://beatport.com/track/test/12345",
                    cover_url="https://bp.com/cover.jpg",
                    duration_seconds=360,
                ),
                score=0.92,
                bpm_score=1.0,
                key_score=1.0,
                genre_score=0.8,
            ),
        ],
        event_profile=EventProfile(
            avg_bpm=128.0,
            bpm_range=(120.0, 136.0),
            dominant_keys=["8A", "9A"],
            dominant_genres=["Tech House"],
            track_count=3,
        ),
        enriched_count=3,
        total_candidates_searched=20,
        services_used=["beatport"],
    )


class TestRecommendationsEndpoint:
    @patch("app.services.recommendation.llm_hooks.is_llm_available", return_value=False)
    @patch("app.services.recommendation.service.generate_recommendations")
    def test_200_with_valid_response(
        self,
        mock_generate,
        mock_llm_available,
        client: TestClient,
        auth_headers: dict,
        event_with_requests: Event,
        user_with_beatport: User,
    ):
        mock_generate.return_value = _mock_recommendation_result()

        response = client.post(
            f"/api/events/{event_with_requests.code}/recommendations",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "suggestions" in data
        assert "profile" in data
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["title"] == "Suggested Track"
        assert data["suggestions"][0]["score"] == 0.92
        assert data["profile"]["avg_bpm"] == 128.0
        assert data["services_used"] == ["beatport"]
        assert data["llm_available"] is False

    def test_401_without_auth(self, client: TestClient, test_event: Event):
        response = client.post(f"/api/events/{test_event.code}/recommendations")
        assert response.status_code == 401

    def test_404_for_nonexistent_event(self, client: TestClient, auth_headers: dict):
        response = client.post("/api/events/NONEXIST/recommendations", headers=auth_headers)
        assert response.status_code == 404

    def test_503_no_services_connected(
        self,
        client: TestClient,
        auth_headers: dict,
        event_with_requests: Event,
    ):
        """User has no Tidal or Beatport linked."""
        response = client.post(
            f"/api/events/{event_with_requests.code}/recommendations",
            headers=auth_headers,
        )
        assert response.status_code == 503
        assert "music services" in response.json()["detail"].lower()

    @patch("app.services.recommendation.service.generate_recommendations")
    @patch(
        "app.services.recommendation.service._soundcharts_related_available",
        return_value=True,
    )
    def test_200_no_service_but_soundcharts_related_enabled(
        self,
        mock_available,
        mock_generate,
        client: TestClient,
        auth_headers: dict,
        event_with_requests: Event,
    ):
        """Issue #556: with no Tidal/Beatport but the Soundcharts related-tracks
        source enabled, the endpoint serves recommendations instead of 503."""
        mock_generate.return_value = RecommendationResult(
            suggestions=[],
            event_profile=EventProfile(track_count=0),
            enriched_count=0,
            total_candidates_searched=1,
            services_used=["soundcharts"],
        )

        response = client.post(
            f"/api/events/{event_with_requests.code}/recommendations",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["services_used"] == ["soundcharts"]

    @patch("app.services.recommendation.service.generate_recommendations")
    def test_200_empty_suggestions_no_requests(
        self,
        mock_generate,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        user_with_beatport: User,
    ):
        mock_generate.return_value = RecommendationResult(
            suggestions=[],
            event_profile=EventProfile(track_count=0),
            enriched_count=0,
            total_candidates_searched=0,
            services_used=["beatport"],
        )

        response = client.post(
            f"/api/events/{test_event.code}/recommendations",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["suggestions"] == []
        assert data["profile"]["track_count"] == 0

    def test_403_non_owner(
        self,
        client: TestClient,
        db: Session,
        test_event: Event,
    ):
        """Another user cannot get recommendations for someone else's event."""
        from app.services.auth import get_password_hash

        other_user = User(
            username="otheruser",
            password_hash=get_password_hash("otherpassword123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        login_resp = client.post(
            "/api/auth/login",
            data={"username": "otheruser", "password": "otherpassword123"},
        )
        other_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        response = client.post(
            f"/api/events/{test_event.code}/recommendations",
            headers=other_headers,
        )
        assert response.status_code == 404  # get_owned_event returns 404 for non-owner

    @patch("app.services.recommendation.service.generate_recommendations")
    def test_response_schema_structure(
        self,
        mock_generate,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        user_with_beatport: User,
    ):
        mock_generate.return_value = _mock_recommendation_result()

        response = client.post(
            f"/api/events/{test_event.code}/recommendations",
            headers=auth_headers,
        )
        data = response.json()

        # Verify all fields present
        suggestion = data["suggestions"][0]
        assert "title" in suggestion
        assert "artist" in suggestion
        assert "bpm" in suggestion
        assert "key" in suggestion
        assert "genre" in suggestion
        assert "score" in suggestion
        assert "bpm_score" in suggestion
        assert "key_score" in suggestion
        assert "genre_score" in suggestion
        assert "source" in suggestion
        assert "track_id" in suggestion
        assert "url" in suggestion
        assert "cover_url" in suggestion

        profile = data["profile"]
        assert "avg_bpm" in profile
        assert "bpm_range_low" in profile
        assert "bpm_range_high" in profile
        assert "dominant_keys" in profile
        assert "dominant_genres" in profile
        assert "track_count" in profile
        assert "enriched_count" in profile

        assert "services_used" in data
        assert "total_candidates_searched" in data
        assert "llm_available" in data
