from app.models.track import Track


def test_track_table_and_columns():
    cols = Track.__table__.columns.keys()
    for expected in (
        "isrc",
        "signature",
        "title",
        "artist",
        "soundcharts_uuid",
        "bpm",
        "musical_key",
        "camelot",
        "genre",
        "duration_sec",
        "energy",
        "danceability",
        "valence",
        "acousticness",
        "instrumentalness",
        "speechiness",
        "liveness",
        "loudness_db",
        "time_signature",
        "explicit",
        "artwork_url",
        "provenance",
        "created_at",
        "updated_at",
    ):
        assert expected in cols, f"missing column {expected}"
    assert Track.__tablename__ == "tracks"
    assert Track.__table__.columns["signature"].nullable is False
    assert Track.__table__.columns["isrc"].nullable is True


def test_track_unique_constraints():
    names = {c.name for c in Track.__table__.constraints}
    assert "uq_tracks_isrc" in names
    assert "uq_tracks_signature" in names
