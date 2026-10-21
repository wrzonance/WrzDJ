from app.core.track_ids import normalize_isrc, valid_isrc


def test_track_id_helpers_normalize_and_validate_isrcs():
    assert normalize_isrc(" us-um7-1900764 ") == "USUM71900764"
    assert valid_isrc("us-um7-1900764") == "USUM71900764"
    assert valid_isrc("not-an-isrc") is None
