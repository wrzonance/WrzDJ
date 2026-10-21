from app.services.tracks.identity import dedupe_signature


def test_dedupe_signature_uses_normalized_track_identity():
    assert dedupe_signature("A feat. B", "Song (Original Mix)") == dedupe_signature(
        "A featuring B", "Song"
    )
