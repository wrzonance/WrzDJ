from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.services.guest_names import generate_unique_nickname


def test_generates_titlecased_no_hyphen(db, test_event: Event):
    nick = generate_unique_nickname(db, event_id=test_event.id)
    assert nick
    assert "-" not in nick
    assert nick[0].isupper()
    assert len(nick) <= 30


def test_avoids_existing_nickname_in_event(db, test_event: Event, monkeypatch):
    # Force the 2-word generator to always collide, proving the suffix/retry path.
    import app.services.guest_names as gn

    guest = Guest(token="g" * 64, fingerprint_hash="fp_x")
    db.add(guest)
    db.commit()
    db.add(GuestProfile(event_id=test_event.id, guest_id=guest.id, nickname="Taken"))
    db.commit()

    calls = {"n": 0}

    def fake_slug(n):
        if n == 2:
            calls["n"] += 1
            return "taken"  # always collides at 2 words
        return "unique-three-words"  # 3-word fallback

    monkeypatch.setattr(gn, "generate_slug", fake_slug)
    nick = generate_unique_nickname(db, event_id=test_event.id, max_attempts=3)
    # Either a digit-suffixed "Taken##" or the 3-word fallback; never bare "Taken".
    assert nick.lower() != "taken"
