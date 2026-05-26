"""Unit tests for export service."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.services.export import (
    export_requests_to_csv,
    generate_export_filename,
    sanitize_csv_value,
    sanitize_filename,
)


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_removes_special_characters(self):
        """Test that special characters are removed."""
        assert sanitize_filename('test<>:"/\\|?*file') == "testfile"

    def test_replaces_spaces_with_underscores(self):
        """Test that spaces are replaced with underscores."""
        assert sanitize_filename("my event name") == "my_event_name"

    def test_limits_length(self):
        """Test that filename is limited to 50 characters."""
        long_name = "a" * 100
        result = sanitize_filename(long_name)
        assert len(result) == 50

    def test_preserves_alphanumeric(self):
        """Test that alphanumeric characters are preserved."""
        assert sanitize_filename("Test123") == "Test123"

    def test_combined_sanitization(self):
        """Test combined special chars, spaces, and length."""
        name = 'My "Special" Event: Live! at the Club?'
        result = sanitize_filename(name)
        assert "<" not in result
        assert ">" not in result
        assert '"' not in result
        assert ":" not in result
        assert "?" not in result
        assert " " not in result
        assert "_" in result


class TestGenerateExportFilename:
    """Tests for export filename generation."""

    def test_includes_event_code(self):
        """Test that filename includes event code."""
        event = MagicMock()
        event.code = "ABC123"
        event.name = "Test Event"

        filename = generate_export_filename(event)
        assert "ABC123" in filename

    def test_includes_sanitized_name(self):
        """Test that filename includes sanitized event name."""
        event = MagicMock()
        event.code = "ABC123"
        event.name = "My Event"

        filename = generate_export_filename(event)
        assert "My_Event" in filename

    def test_includes_date(self):
        """Test that filename includes current date."""
        event = MagicMock()
        event.code = "ABC123"
        event.name = "Test"

        filename = generate_export_filename(event)
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        assert date_str in filename

    def test_ends_with_csv_extension(self):
        """Test that filename ends with .csv."""
        event = MagicMock()
        event.code = "ABC123"
        event.name = "Test"

        filename = generate_export_filename(event)
        assert filename.endswith(".csv")


class TestExportRequestsToCsv:
    """Tests for CSV export functionality."""

    def test_includes_header_row(self):
        """Test that CSV includes header row."""
        event = MagicMock()
        csv_content = export_requests_to_csv(event, [])

        assert "Request ID" in csv_content
        assert "Song Title" in csv_content
        assert "Artist" in csv_content
        assert "Genre" in csv_content
        assert "BPM" in csv_content
        assert "Key" in csv_content
        assert "Votes" in csv_content
        assert "Status" in csv_content
        assert "Note" in csv_content
        assert "Source" in csv_content
        assert "Source URL" in csv_content
        assert "Artwork URL" in csv_content
        assert "Created At" in csv_content
        assert "Updated At" in csv_content

    def test_empty_requests_list(self):
        """Test exporting empty requests list."""
        event = MagicMock()
        csv_content = export_requests_to_csv(event, [])

        lines = csv_content.strip().split("\n")
        assert len(lines) == 1  # Just header

    def test_includes_request_data(self):
        """Test that CSV includes request data."""
        event = MagicMock()

        request = MagicMock()
        request.id = 42
        request.song_title = "Test Song"
        request.artist = "Test Artist"
        request.genre = "House"
        request.bpm = 128.0
        request.musical_key = "8A"
        request.vote_count = 5
        request.status = "accepted"
        request.note = "Great song!"
        request.source = "spotify"
        request.source_url = "https://spotify.com/track/123"
        request.artwork_url = "https://i.scdn.co/image/abc123"
        request.created_at = datetime(2026, 1, 15, 12, 0, 0)
        request.updated_at = datetime(2026, 1, 15, 12, 30, 0)

        csv_content = export_requests_to_csv(event, [request])

        assert "42" in csv_content
        assert "Test Song" in csv_content
        assert "Test Artist" in csv_content
        assert "House" in csv_content
        assert "128.0" in csv_content
        assert "8A" in csv_content
        assert "5" in csv_content
        assert "accepted" in csv_content
        assert "Great song!" in csv_content
        assert "spotify" in csv_content
        assert "https://spotify.com/track/123" in csv_content
        assert "https://i.scdn.co/image/abc123" in csv_content
        assert "2026-01-15" in csv_content

    def test_handles_none_values(self):
        """Test that None values are handled gracefully."""
        event = MagicMock()

        request = MagicMock()
        request.id = 1
        request.song_title = "Song"
        request.artist = "Artist"
        request.genre = None
        request.bpm = None
        request.musical_key = None
        request.vote_count = 0
        request.status = "new"
        request.note = None
        request.source = None
        request.source_url = None
        request.artwork_url = None
        request.created_at = None
        request.updated_at = None

        # Should not raise
        csv_content = export_requests_to_csv(event, [request])
        assert "Song" in csv_content

    def test_multiple_requests(self):
        """Test exporting multiple requests."""
        event = MagicMock()

        requests = []
        for i in range(5):
            req = MagicMock()
            req.id = i
            req.song_title = f"Song {i}"
            req.artist = f"Artist {i}"
            req.genre = None
            req.bpm = None
            req.musical_key = None
            req.vote_count = 0
            req.status = "new"
            req.note = None
            req.source = "manual"
            req.source_url = None
            req.artwork_url = None
            req.created_at = datetime(2026, 1, 15, 12, 0, 0)
            req.updated_at = datetime(2026, 1, 15, 12, 0, 0)
            requests.append(req)

        csv_content = export_requests_to_csv(event, requests)

        lines = csv_content.strip().split("\n")
        assert len(lines) == 6  # Header + 5 data rows

    def test_escapes_csv_special_characters(self):
        """Test that CSV special characters are properly escaped."""
        event = MagicMock()

        request = MagicMock()
        request.id = 1
        request.song_title = 'Song with "quotes" and, commas'
        request.artist = "Artist\nwith\nnewlines"
        request.genre = None
        request.bpm = None
        request.musical_key = None
        request.vote_count = 0
        request.status = "new"
        request.note = None
        request.source = "manual"
        request.source_url = None
        request.artwork_url = None
        request.created_at = datetime(2026, 1, 15, 12, 0, 0)
        request.updated_at = datetime(2026, 1, 15, 12, 0, 0)

        # Should not raise and should produce valid CSV
        csv_content = export_requests_to_csv(event, [request])
        assert "Song with" in csv_content

    def test_includes_enriched_metadata(self):
        """Test that CSV includes genre, BPM, key, votes, and artwork URL."""
        event = MagicMock()

        request = MagicMock()
        request.id = 10
        request.song_title = "Strobe"
        request.artist = "Deadmau5"
        request.genre = "Progressive House"
        request.bpm = 128.0
        request.musical_key = "2A"
        request.vote_count = 12
        request.status = "accepted"
        request.note = None
        request.source = "beatport"
        request.source_url = "https://www.beatport.com/track/strobe/123"
        request.artwork_url = "https://geo-media.beatport.com/image/abc.jpg"
        request.created_at = datetime(2026, 3, 20, 22, 0, 0)
        request.updated_at = datetime(2026, 3, 20, 22, 5, 0)

        csv_content = export_requests_to_csv(event, [request])

        lines = csv_content.strip().split("\n")
        assert len(lines) == 2  # Header + 1 data row
        data_line = lines[1]
        assert "Progressive House" in data_line
        assert "128.0" in data_line
        assert "2A" in data_line
        assert "12" in data_line
        assert "https://geo-media.beatport.com/image/abc.jpg" in data_line

    def test_none_metadata_produces_empty_cells(self):
        """Test that missing enrichment data produces empty CSV cells, not 'None'."""
        event = MagicMock()

        request = MagicMock()
        request.id = 1
        request.song_title = "Unknown Track"
        request.artist = "Unknown Artist"
        request.genre = None
        request.bpm = None
        request.musical_key = None
        request.vote_count = None
        request.status = "new"
        request.note = None
        request.source = "manual"
        request.source_url = None
        request.artwork_url = None
        request.created_at = datetime(2026, 3, 20, 22, 0, 0)
        request.updated_at = datetime(2026, 3, 20, 22, 0, 0)

        csv_content = export_requests_to_csv(event, [request])

        # "None" should never appear as literal text in the CSV
        assert "None" not in csv_content


class TestSanitizeCsvValue:
    """Tests for CSV formula injection protection."""

    def test_sanitizes_equals_sign(self):
        """Test that values starting with = are escaped."""
        result = sanitize_csv_value('=HYPERLINK("http://evil.com")')
        assert result.startswith("'")
        assert "=HYPERLINK" in result

    def test_sanitizes_plus_sign(self):
        """Test that values starting with + are escaped."""
        result = sanitize_csv_value("+cmd|' /C calc'!A0")
        assert result.startswith("'")

    def test_sanitizes_minus_sign(self):
        """Test that values starting with - are escaped."""
        result = sanitize_csv_value("-2+3+cmd|' /C calc'!A0")
        assert result.startswith("'")

    def test_sanitizes_at_sign(self):
        """Test that values starting with @ are escaped."""
        result = sanitize_csv_value("@SUM(1+1)")
        assert result.startswith("'")

    def test_sanitizes_tab_character(self):
        """Test that values starting with tab are escaped."""
        result = sanitize_csv_value("\tmalicious")
        assert result.startswith("'")

    def test_sanitizes_carriage_return(self):
        """Test that values starting with CR are escaped."""
        result = sanitize_csv_value("\rmalicious")
        assert result.startswith("'")

    def test_sanitizes_line_feed(self):
        """Leading LF is escaped — importers may strip it then evaluate the formula."""
        result = sanitize_csv_value("\n=cmd|' /C calc'!A0")
        assert result.startswith("'")

    def test_preserves_normal_values(self):
        """Test that normal values are not modified."""
        assert sanitize_csv_value("Normal Song Title") == "Normal Song Title"
        assert sanitize_csv_value("Artist Name") == "Artist Name"
        assert sanitize_csv_value("https://spotify.com/track") == "https://spotify.com/track"

    def test_handles_none(self):
        """Test that None values return empty string."""
        assert sanitize_csv_value(None) == ""

    def test_handles_empty_string(self):
        """Test that empty string returns empty string."""
        assert sanitize_csv_value("") == ""

    def test_export_sanitizes_user_input(self):
        """Test that export_requests_to_csv sanitizes user-controlled fields."""
        event = MagicMock()

        request = MagicMock()
        request.id = 1
        request.song_title = '=HYPERLINK("http://evil.com","Click")'
        request.artist = "+cmd|' /C calc'!A0"
        request.genre = None
        request.bpm = None
        request.musical_key = None
        request.vote_count = 0
        request.status = "new"
        request.note = "-2+3+cmd"
        request.source = "@SUM(1+1)"
        request.source_url = None
        request.artwork_url = None
        request.created_at = datetime(2026, 1, 15, 12, 0, 0)
        request.updated_at = datetime(2026, 1, 15, 12, 0, 0)

        csv_content = export_requests_to_csv(event, [request])

        # All formula characters should be escaped with leading quote
        lines = csv_content.strip().split("\n")
        data_line = lines[1]

        # Verify the raw formula chars are escaped (preceded by ')
        assert "'=" in data_line or "\"'=" in data_line
        assert "'+" in data_line or "\"'+" in data_line
        assert "'-" in data_line or "\"'-" in data_line
        assert "'@" in data_line or "\"'@" in data_line


class TestExportPlayHistoryToCsv:
    """Tests for play history CSV export functionality."""

    def test_includes_header_row(self):
        """Test that CSV includes proper header row for play history."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()
        csv_content = export_play_history_to_csv(event, [])

        assert "Play Order" in csv_content
        assert "Title" in csv_content
        assert "Artist" in csv_content
        assert "Album" in csv_content
        assert "Source" in csv_content
        assert "Was Requested" in csv_content
        assert "Started At" in csv_content
        assert "Ended At" in csv_content

    def test_empty_history_list(self):
        """Test exporting empty play history list."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()
        csv_content = export_play_history_to_csv(event, [])

        lines = csv_content.strip().split("\n")
        assert len(lines) == 1  # Just header

    def test_includes_play_history_data(self):
        """Test that CSV includes play history data."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = "Test Song"
        history_item.artist = "Test Artist"
        history_item.album = "Test Album"
        history_item.source = "stagelinq"
        history_item.matched_request_id = 42
        history_item.started_at = datetime(2026, 1, 15, 12, 0, 0)
        history_item.ended_at = datetime(2026, 1, 15, 12, 3, 30)

        csv_content = export_play_history_to_csv(event, [history_item])

        assert "1" in csv_content  # play_order
        assert "Test Song" in csv_content
        assert "Test Artist" in csv_content
        assert "Test Album" in csv_content
        assert "Live" in csv_content  # stagelinq -> "Live"
        assert "Yes" in csv_content  # matched_request_id present -> "Yes"
        assert "2026-01-15" in csv_content

    def test_source_display_stagelinq_as_live(self):
        """Test that stagelinq source displays as 'Live'."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = "Song"
        history_item.artist = "Artist"
        history_item.album = None
        history_item.source = "stagelinq"
        history_item.matched_request_id = None
        history_item.started_at = datetime(2026, 1, 15, 12, 0, 0)
        history_item.ended_at = None

        csv_content = export_play_history_to_csv(event, [history_item])

        lines = csv_content.strip().split("\n")
        data_line = lines[1]
        assert "Live" in data_line

    def test_source_display_manual_as_manual(self):
        """Test that manual source displays as 'Manual'."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = "Song"
        history_item.artist = "Artist"
        history_item.album = None
        history_item.source = "manual"
        history_item.matched_request_id = 10
        history_item.started_at = datetime(2026, 1, 15, 12, 0, 0)
        history_item.ended_at = None

        csv_content = export_play_history_to_csv(event, [history_item])

        lines = csv_content.strip().split("\n")
        data_line = lines[1]
        assert "Manual" in data_line

    def test_was_requested_yes_when_matched(self):
        """Test that Was Requested shows 'Yes' when matched_request_id is set."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = "Song"
        history_item.artist = "Artist"
        history_item.album = None
        history_item.source = "stagelinq"
        history_item.matched_request_id = 42
        history_item.started_at = datetime(2026, 1, 15, 12, 0, 0)
        history_item.ended_at = None

        csv_content = export_play_history_to_csv(event, [history_item])

        lines = csv_content.strip().split("\n")
        data_line = lines[1]
        assert "Yes" in data_line

    def test_was_requested_no_when_not_matched(self):
        """Test that Was Requested shows 'No' when matched_request_id is None."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = "Song"
        history_item.artist = "Artist"
        history_item.album = None
        history_item.source = "stagelinq"
        history_item.matched_request_id = None
        history_item.started_at = datetime(2026, 1, 15, 12, 0, 0)
        history_item.ended_at = None

        csv_content = export_play_history_to_csv(event, [history_item])

        lines = csv_content.strip().split("\n")
        data_line = lines[1]
        assert "No" in data_line

    def test_handles_none_values(self):
        """Test that None values are handled gracefully."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = "Song"
        history_item.artist = "Artist"
        history_item.album = None
        history_item.source = "stagelinq"
        history_item.matched_request_id = None
        history_item.started_at = None
        history_item.ended_at = None

        # Should not raise
        csv_content = export_play_history_to_csv(event, [history_item])
        assert "Song" in csv_content

    def test_multiple_history_entries(self):
        """Test exporting multiple play history entries."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_items = []
        for i in range(5):
            item = MagicMock()
            item.play_order = i + 1
            item.title = f"Song {i}"
            item.artist = f"Artist {i}"
            item.album = f"Album {i}" if i % 2 == 0 else None
            item.source = "stagelinq" if i % 2 == 0 else "manual"
            item.matched_request_id = i if i % 2 == 0 else None
            item.started_at = datetime(2026, 1, 15, 12, i, 0)
            item.ended_at = datetime(2026, 1, 15, 12, i + 3, 0)
            history_items.append(item)

        csv_content = export_play_history_to_csv(event, history_items)

        lines = csv_content.strip().split("\n")
        assert len(lines) == 6  # Header + 5 data rows

    def test_sanitizes_formula_injection(self):
        """Test that play history export sanitizes user-controlled fields."""
        from app.services.export import export_play_history_to_csv

        event = MagicMock()

        history_item = MagicMock()
        history_item.play_order = 1
        history_item.title = '=HYPERLINK("http://evil.com","Click")'
        history_item.artist = "+cmd|' /C calc'!A0"
        history_item.album = "-2+3+cmd"
        history_item.source = "stagelinq"
        history_item.matched_request_id = None
        history_item.started_at = datetime(2026, 1, 15, 12, 0, 0)
        history_item.ended_at = None

        csv_content = export_play_history_to_csv(event, [history_item])

        lines = csv_content.strip().split("\n")
        data_line = lines[1]

        # All formula characters should be escaped with leading quote
        assert "'=" in data_line or "\"'=" in data_line
        assert "'+" in data_line or "\"'+" in data_line
        assert "'-" in data_line or "\"'-" in data_line


class TestGeneratePlayHistoryExportFilename:
    """Tests for play history export filename generation."""

    def test_includes_event_code(self):
        """Test that filename includes event code."""
        from app.services.export import generate_play_history_export_filename

        event = MagicMock()
        event.code = "ABC123"
        event.name = "Test Event"

        filename = generate_play_history_export_filename(event)
        assert "ABC123" in filename

    def test_includes_play_history_indicator(self):
        """Test that filename indicates it's play history."""
        from app.services.export import generate_play_history_export_filename

        event = MagicMock()
        event.code = "ABC123"
        event.name = "Test"

        filename = generate_play_history_export_filename(event)
        assert "play_history" in filename.lower()

    def test_ends_with_csv_extension(self):
        """Test that filename ends with .csv."""
        from app.services.export import generate_play_history_export_filename

        event = MagicMock()
        event.code = "ABC123"
        event.name = "Test"

        filename = generate_play_history_export_filename(event)
        assert filename.endswith(".csv")
