"""Now-playing service tests grouped by lifecycle behavior."""

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.services.now_playing import fuzzy_match_pending_request
from app.services.track_normalizer import fuzzy_match_score, normalize_artist, normalize_track_title


class TestFuzzyMatchScore:
    """Tests for fuzzy_match_score function."""

    def test_exact_match(self):
        """Exact matches return 1.0."""
        assert fuzzy_match_score("Blue Monday", "Blue Monday") == 1.0

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        assert fuzzy_match_score("BLUE MONDAY", "blue monday") == 1.0

    def test_whitespace_trimmed(self):
        """Leading/trailing whitespace is trimmed."""
        assert fuzzy_match_score("  Blue Monday  ", "Blue Monday") == 1.0

    def test_partial_match(self):
        """Similar strings return scores above 0.5."""
        score = fuzzy_match_score("Blue Monday", "Blue Monday (Original)")
        assert 0.5 < score < 1.0

    def test_no_match(self):
        """Completely different strings return low scores."""
        score = fuzzy_match_score("Blue Monday", "Sandstorm")
        assert score < 0.3


class TestNormalizeTrackTitle:
    """Tests for normalize_track_title function."""

    def test_strips_original_mix(self):
        assert normalize_track_title("Banana (Original Mix)") == "Banana"

    def test_strips_extended_mix(self):
        assert normalize_track_title("Banana (Extended Mix)") == "Banana"

    def test_strips_radio_edit(self):
        assert normalize_track_title("Banana (Radio Edit)") == "Banana"

    def test_strips_club_mix(self):
        assert normalize_track_title("Banana (Club Mix)") == "Banana"

    def test_strips_album_version(self):
        assert normalize_track_title("Banana (Album Version)") == "Banana"

    def test_strips_single_version(self):
        assert normalize_track_title("Banana (Single Version)") == "Banana"

    def test_strips_full_length(self):
        assert normalize_track_title("Banana (Full Length)") == "Banana"

    def test_strips_full_length_version(self):
        assert normalize_track_title("Banana (Full Length Version)") == "Banana"

    def test_strips_main_mix(self):
        assert normalize_track_title("Banana (Main Mix)") == "Banana"

    def test_strips_short_edit(self):
        assert normalize_track_title("Banana (Short Edit)") == "Banana"

    def test_strips_long_mix(self):
        assert normalize_track_title("Banana (Long Mix)") == "Banana"

    def test_strips_original_version(self):
        assert normalize_track_title("Banana (Original Version)") == "Banana"

    def test_strips_bare_original(self):
        assert normalize_track_title("Banana (Original)") == "Banana"

    def test_strips_bare_extended(self):
        assert normalize_track_title("Banana (Extended)") == "Banana"

    def test_strips_bracket_variant(self):
        assert normalize_track_title("Banana [Original Mix]") == "Banana"

    def test_strips_dash_radio_edit(self):
        assert normalize_track_title("Banana - Radio Edit") == "Banana"

    def test_strips_dash_original_mix(self):
        assert normalize_track_title("Banana - Original Mix") == "Banana"

    def test_case_insensitive(self):
        assert normalize_track_title("Banana (ORIGINAL MIX)") == "Banana"
        assert normalize_track_title("Banana (original mix)") == "Banana"

    def test_keeps_named_remix(self):
        assert normalize_track_title("Banana (Skrillex Remix)") == "Banana (Skrillex Remix)"

    def test_keeps_vip(self):
        assert normalize_track_title("Banana (VIP)") == "Banana (VIP)"

    def test_keeps_instrumental(self):
        assert normalize_track_title("Banana (Instrumental)") == "Banana (Instrumental)"

    def test_keeps_acoustic(self):
        assert normalize_track_title("Banana (Acoustic)") == "Banana (Acoustic)"

    def test_keeps_live(self):
        assert normalize_track_title("Banana (Live)") == "Banana (Live)"

    def test_keeps_dub_mix(self):
        assert normalize_track_title("Banana (Dub Mix)") == "Banana (Dub Mix)"

    def test_keeps_a_cappella(self):
        assert normalize_track_title("Banana (A Cappella)") == "Banana (A Cappella)"

    def test_keeps_remaster(self):
        assert normalize_track_title("Banana (2024 Remaster)") == "Banana (2024 Remaster)"

    def test_empty_string(self):
        assert normalize_track_title("") == ""

    def test_whitespace_only(self):
        assert normalize_track_title("   ") == ""

    def test_no_suffix(self):
        assert normalize_track_title("Just a Song") == "Just a Song"

    def test_multiple_parenthetical_strips_generic_only(self):
        result = normalize_track_title("Banana (Skrillex Remix) (Original Mix)")
        assert result == "Banana (Skrillex Remix)"


class TestNormalizeArtist:
    """Tests for normalize_artist function."""

    def test_normalizes_featuring(self):
        assert normalize_artist("Drake featuring Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_feat_no_dot(self):
        assert normalize_artist("Drake feat Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_feat_dot(self):
        assert normalize_artist("Drake feat. Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_ft_no_dot(self):
        assert normalize_artist("Drake ft Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_ft_dot(self):
        assert normalize_artist("Drake ft. Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_with(self):
        assert normalize_artist("Drake with Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_capitalized(self):
        assert normalize_artist("Drake Featuring Rihanna") == "Drake feat. Rihanna"

    def test_no_false_positive_daft(self):
        """Should not match 'ft' inside words like 'Daft'."""
        assert normalize_artist("Daft Punk") == "Daft Punk"

    def test_empty_string(self):
        assert normalize_artist("") == ""

    def test_whitespace_only(self):
        assert normalize_artist("   ") == ""

    def test_no_featuring(self):
        assert normalize_artist("New Order") == "New Order"


class TestFuzzyMatchPendingRequest:
    """Tests for fuzzy_match_pending_request function."""

    def test_exact_match(self, db: Session, test_event: Event, accepted_request: Request):
        """Finds exact match in accepted requests."""
        result = fuzzy_match_pending_request(db, test_event.id, "Blue Monday", "New Order")
        assert result is not None
        assert result.id == accepted_request.id

    def test_match_with_original_mix_suffix(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Matches when DJ equipment reports '(Original Mix)' suffix."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday (Original Mix)", "New Order"
        )
        assert result is not None
        assert result.id == accepted_request.id

    def test_match_with_extended_mix_suffix(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Matches when DJ equipment reports '(Extended Mix)' suffix."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday (Extended Mix)", "New Order"
        )
        assert result is not None
        assert result.id == accepted_request.id

    def test_match_with_dash_radio_edit(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Matches when DJ equipment reports '- Radio Edit' suffix."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday - Radio Edit", "New Order"
        )
        assert result is not None
        assert result.id == accepted_request.id

    def test_no_match_named_remix(self, db: Session, test_event: Event, accepted_request: Request):
        """Does NOT match when it's a genuinely different version (named remix)."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday (Hardfloor Remix)", "New Order"
        )
        # Named remix changes the title enough that it shouldn't match "Blue Monday"
        # (fuzzy score of normalized titles will differ)
        assert result is None

    def test_match_feat_vs_featuring(self, db: Session, test_event: Event):
        """Matches artist with 'feat.' vs 'featuring'."""
        req = Request(
            event_id=test_event.id,
            song_title="One Dance",
            artist="Drake featuring Wizkid",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="feat_test_key",
        )
        db.add(req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "One Dance", "Drake feat. Wizkid")
        assert result is not None
        assert result.id == req.id

    def test_match_feat_embedded_in_title_multi_artist(self, db: Session, test_event: Event):
        """Regression (prod event RMLNDZ / request #491): the bridge reported
        'Get Low (ft. Ying Yang Twins)' by 'Lil Jon & The Eastside Boyz' while
        the accepted request was 'Get Low' by
        'Lil Jon, The EastSide Boyz, Ying Yang Twins'. The featured artist
        embedded in the title tanked the fuzzy score below threshold, so the
        request was never auto-matched/marked played.
        """
        req = Request(
            event_id=test_event.id,
            song_title="Get Low",
            artist="Lil Jon, The EastSide Boyz, Ying Yang Twins",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="get_low_feat_title_key",
        )
        db.add(req)
        db.commit()

        result = fuzzy_match_pending_request(
            db,
            test_event.id,
            "Get Low (ft. Ying Yang Twins)",
            "Lil Jon & The Eastside Boyz",
        )
        assert result is not None
        assert result.id == req.id

    def test_match_primary_artist_only_vs_multi_artist_request(
        self, db: Session, test_event: Event
    ):
        """Equipment often reports only the primary artist while the guest
        request lists every collaborator. Multi-artist-aware scoring must let
        'Lil Jon' match 'Lil Jon, The EastSide Boyz, Ying Yang Twins'.
        """
        req = Request(
            event_id=test_event.id,
            song_title="Get Low",
            artist="Lil Jon, The EastSide Boyz, Ying Yang Twins",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="get_low_primary_only_key",
        )
        db.add(req)
        db.commit()

        result = fuzzy_match_pending_request(
            db, test_event.id, "Get Low (ft. Ying Yang Twins)", "Lil Jon"
        )
        assert result is not None
        assert result.id == req.id

    def test_matches_new_requests(self, db: Session, test_event: Event):
        """Matches NEW requests (not just ACCEPTED)."""
        new_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="new_req_key",
        )
        db.add(new_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is not None
        assert result.id == new_req.id

    def test_prefers_accepted_over_new(self, db: Session, test_event: Event):
        """Prefers ACCEPTED over NEW when both match equally."""
        new_req = Request(
            event_id=test_event.id,
            song_title="Levels",
            artist="Avicii",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="levels_new_key",
        )
        accepted_req = Request(
            event_id=test_event.id,
            song_title="Levels",
            artist="Avicii",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="levels_accepted_key",
        )
        db.add(new_req)
        db.add(accepted_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Levels", "Avicii")
        assert result is not None
        assert result.id == accepted_req.id

    def test_does_not_match_playing(self, db: Session, test_event: Event):
        """Does not match PLAYING requests."""
        playing_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            status=RequestStatus.PLAYING.value,
            dedupe_key="playing_key",
        )
        db.add(playing_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None

    def test_does_not_match_played(self, db: Session, test_event: Event):
        """Does not match PLAYED requests."""
        played_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            status=RequestStatus.PLAYED.value,
            dedupe_key="played_key",
        )
        db.add(played_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None

    def test_does_not_match_rejected(self, db: Session, test_event: Event):
        """Does not match REJECTED requests."""
        rejected_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            status=RequestStatus.REJECTED.value,
            dedupe_key="rejected_key",
        )
        db.add(rejected_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None

    def test_no_match_below_threshold(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Returns None when no match above threshold."""
        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None
