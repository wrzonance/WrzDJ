"""Event API tests grouped by behavior."""

from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.auth import get_password_hash


class TestCsvExport:
    """Tests for CSV export functionality."""

    def test_export_csv_reports_truncation_at_the_request_limit(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        test_request: Request,
        db: Session,
    ):
        from app.api.events_exports import MAX_EXPORT_REQUESTS

        for row_count, expected_truncated in (
            (MAX_EXPORT_REQUESTS, "false"),
            (MAX_EXPORT_REQUESTS + 1, "true"),
        ):
            rows = [test_request] * row_count
            with (
                patch(
                    "app.api.events_exports.get_requests_for_event", return_value=rows
                ) as get_requests,
                patch(
                    "app.api.events_exports.export_requests_to_csv", return_value="csv\n"
                ) as export_csv,
            ):
                response = client.get(
                    f"/api/events/{test_event.code}/export/csv",
                    headers=auth_headers,
                )

            assert response.status_code == 200
            assert response.headers["x-export-truncated"] == expected_truncated
            get_requests.assert_called_once_with(
                db,
                test_event,
                status=None,
                since=None,
                limit=MAX_EXPORT_REQUESTS + 1,
            )
            export_csv.assert_called_once_with(test_event, rows[:MAX_EXPORT_REQUESTS])

    def test_export_play_history_reports_truncation_at_the_history_limit(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        from app.api.events_exports import MAX_EXPORT_PLAY_HISTORY
        from app.models.play_history import PlayHistory

        row = PlayHistory(
            event_id=test_event.id,
            title="Export row",
            artist="Artist",
            source="manual",
            play_order=1,
        )
        for total, expected_truncated in (
            (MAX_EXPORT_PLAY_HISTORY, "false"),
            (MAX_EXPORT_PLAY_HISTORY + 1, "true"),
        ):
            rows = [row] * min(total, MAX_EXPORT_PLAY_HISTORY)
            with (
                patch("app.api.events_exports.get_play_history", return_value=(rows, total)),
                patch(
                    "app.api.events_exports.export_play_history_to_csv", return_value="csv\n"
                ) as export_csv,
            ):
                response = client.get(
                    f"/api/events/{test_event.code}/export/play-history/csv",
                    headers=auth_headers,
                )

            assert response.status_code == 200
            assert response.headers["x-export-truncated"] == expected_truncated
            export_csv.assert_called_once_with(test_event, rows)

    def test_export_csv_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test exporting event requests as CSV."""
        # Add a request to the event
        req = Request(
            event_id=test_event.id,
            song_title="Export Test Song",
            artist="Export Artist",
            source="manual",
            status=RequestStatus.NEW.value,
            note="Test note",
            dedupe_key="export_dedupe_key_123",
        )
        db.add(req)
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert test_event.code in response.headers["content-disposition"]

        # Verify CSV content
        content = response.text
        assert "Request ID" in content
        assert "Song Title" in content
        assert "Export Test Song" in content
        assert "Export Artist" in content
        assert "Test note" in content

    def test_export_csv_filename_header_safely_encodes_unicode_and_controls(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        test_event.name = "日本語 😄\r\nX-Injected: yes"
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "\r" not in disposition
        assert "\n" not in disposition
        assert "x-injected" not in response.headers
        assert "X-Injected: yes" not in disposition
        assert "filename*=UTF-8''" in disposition
        assert 'filename="' in disposition
        assert all(ord(character) < 128 for character in disposition)

    def test_export_csv_no_auth(self, client: TestClient, test_event: Event):
        """Test exporting without auth fails."""
        response = client.get(f"/api/events/{test_event.code}/export/csv")
        assert response.status_code == 401

    def test_export_csv_not_owner(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test exporting event you don't own fails."""
        # Create another user and their event

        other_user = User(
            username="otheruser",
            password_hash=get_password_hash("otherpassword"),
        )
        db.add(other_user)
        db.flush()

        other_event = Event(
            code="OTHER1",
            join_code="WX8XQG",
            name="Other User Event",
            created_by_user_id=other_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(other_event)
        db.commit()

        response = client.get(
            f"/api/events/{other_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_export_csv_expired_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export CSV for expired events."""
        expired_event = Event(
            code="EXPCSV",
            join_code="8AQM9R",
            name="Expired CSV Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(
            f"/api/events/{expired_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_export_csv_archived_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export CSV for archived events."""
        archived_event = Event(
            code="ARCSV1",
            join_code="ZT548E",
            name="Archived CSV Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(archived_event)
        db.commit()

        response = client.get(
            f"/api/events/{archived_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_export_csv_empty_event(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test exporting an event with no requests."""
        response = client.get(
            f"/api/events/{test_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content = response.text
        # Should have header row but no data rows
        assert "Request ID" in content
        lines = content.strip().split("\n")
        assert len(lines) == 1  # Just the header


class TestPlayHistoryCsvExport:
    """Tests for play history CSV export functionality."""

    def test_export_play_history_csv_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test exporting play history as CSV."""
        from app.models.play_history import PlayHistory

        # Add play history entries
        entry1 = PlayHistory(
            event_id=test_event.id,
            title="First Song",
            artist="Artist One",
            album="Album One",
            source="stagelinq",
            matched_request_id=None,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=1,
        )
        entry2 = PlayHistory(
            event_id=test_event.id,
            title="Second Song",
            artist="Artist Two",
            album=None,
            source="manual",
            matched_request_id=42,
            started_at=utcnow(),
            ended_at=None,
            play_order=2,
        )
        db.add_all([entry1, entry2])
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert "play_history" in response.headers["content-disposition"]

        # Verify CSV content
        content = response.text
        assert "Title" in content
        assert "Artist" in content
        assert "Source" in content
        assert "Was Requested" in content
        assert "First Song" in content
        assert "Second Song" in content
        assert "Live" in content  # stagelinq -> Live
        assert "Manual" in content  # manual -> Manual

    def test_export_play_history_csv_no_auth(self, client: TestClient, test_event: Event):
        """Test exporting play history without auth fails."""
        response = client.get(f"/api/events/{test_event.code}/export/play-history/csv")
        assert response.status_code == 401

    def test_export_play_history_csv_not_owner(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test exporting play history for event you don't own fails."""

        other_user = User(
            username="otheruser2",
            password_hash=get_password_hash("otherpassword"),
        )
        db.add(other_user)
        db.flush()

        other_event = Event(
            code="OTHER2",
            join_code="7PJBSF",
            name="Other User Event",
            created_by_user_id=other_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(other_event)
        db.commit()

        response = client.get(
            f"/api/events/{other_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_export_play_history_csv_includes_both_sources(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that export includes both stagelinq and manual sources."""
        from app.models.play_history import PlayHistory

        # Add stagelinq entry (live DJ tracking)
        stagelinq_entry = PlayHistory(
            event_id=test_event.id,
            title="Live Track",
            artist="DJ Artist",
            album=None,
            source="stagelinq",
            matched_request_id=None,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=1,
        )
        # Add manual entry (DJ marked request as played)
        manual_entry = PlayHistory(
            event_id=test_event.id,
            title="Requested Track",
            artist="Requested Artist",
            album=None,
            source="manual",
            matched_request_id=99,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=2,
        )
        db.add_all([stagelinq_entry, manual_entry])
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

        content = response.text
        lines = content.strip().split("\n")
        # Header + 2 data rows
        assert len(lines) == 3

        # Verify both sources are present
        assert "Live" in content  # stagelinq -> Live
        assert "Manual" in content  # manual -> Manual

    def test_export_play_history_csv_was_requested_column(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that Was Requested column shows Yes/No correctly."""
        from app.models.play_history import PlayHistory

        # Entry with matched request
        requested = PlayHistory(
            event_id=test_event.id,
            title="Requested Song",
            artist="Artist",
            album=None,
            source="stagelinq",
            matched_request_id=42,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=1,
        )
        # Entry without matched request
        not_requested = PlayHistory(
            event_id=test_event.id,
            title="DJ Choice",
            artist="Artist",
            album=None,
            source="stagelinq",
            matched_request_id=None,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=2,
        )
        db.add_all([requested, not_requested])
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

        content = response.text
        # Both Yes and No should be present
        assert "Yes" in content
        assert "No" in content

    def test_export_play_history_csv_empty(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test exporting play history when no tracks played."""
        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content = response.text
        # Should have header row but no data rows
        assert "Title" in content
        lines = content.strip().split("\n")
        assert len(lines) == 1  # Just the header

    def test_export_play_history_csv_expired_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export play history CSV for expired events."""
        expired_event = Event(
            code="EXPHIS",
            join_code="UDD294",
            name="Expired Play History Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(
            f"/api/events/{expired_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_export_play_history_csv_archived_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export play history CSV for archived events."""
        archived_event = Event(
            code="ARCHIS",
            join_code="X9K3WM",
            name="Archived Play History Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(archived_event)
        db.commit()

        response = client.get(
            f"/api/events/{archived_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
