from app.models.user import User
from app.services.event import create_event


def test_create_event_seeds_from_dj_default(db, test_user: User):
    test_user.frictionless_join_default = True
    db.commit()
    event = create_event(db, "Seeded", test_user)
    assert event.frictionless_join is True


def test_create_event_default_off_when_dj_default_off(db, test_user: User):
    event = create_event(db, "NotSeeded", test_user)
    assert event.frictionless_join is False
