"""Tests for local screenshot-fixture guest seeding."""

from app.models.guest_profile import GuestProfile
from scripts.seed_demo_event import DEMO_GUEST_NICKNAME, reset_demo_guest


def test_seed_demo_guest_uses_fresh_token_for_existing_fixture(db, test_event):
    guest = reset_demo_guest(db, test_event.id)
    first_token = guest.token
    db.add(
        GuestProfile(
            event_id=test_event.id,
            guest_id=guest.id,
            nickname=DEMO_GUEST_NICKNAME,
            submission_count=1,
        )
    )
    db.commit()

    reseeded_guest = reset_demo_guest(db, test_event.id)

    assert reseeded_guest.id == guest.id
    assert reseeded_guest.token != first_token
    assert len(reseeded_guest.token) >= 32
