from app.services.recommendation.scorer import EventProfile


def test_default_event_profile_uses_independent_list_fields():
    first = EventProfile()
    second = EventProfile()

    assert first.dominant_keys == []
    assert first.dominant_genres == []
    assert first.dominant_keys is not second.dominant_keys
    assert first.dominant_genres is not second.dominant_genres
