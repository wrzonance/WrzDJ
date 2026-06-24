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


def test_track_no_redundant_indexes():
    """isrc and signature must NOT have a separate non-unique index.

    The UniqueConstraint already provides an index; a redundant ix_ is waste.
    """
    idx_names = {i.name for i in Track.__table__.indexes}
    assert "ix_tracks_isrc" not in idx_names, "redundant non-unique index on isrc"
    assert "ix_tracks_signature" not in idx_names, "redundant non-unique index on signature"


def test_track_energy_check_constraint_present():
    """CheckConstraint for energy range must exist on the table."""
    from sqlalchemy import CheckConstraint

    check_names = {c.name for c in Track.__table__.constraints if isinstance(c, CheckConstraint)}
    assert "ck_tracks_energy_range" in check_names
