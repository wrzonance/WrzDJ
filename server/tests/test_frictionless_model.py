from app.models.user import User


def test_user_frictionless_default_defaults_false(db):
    user = User(username="dj_fric", password_hash="x", role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.frictionless_join_default is False


def test_event_frictionless_join_defaults_false(db, test_user: User):
    from app.services.event import create_event

    event = create_event(db, "Frictionless Test", test_user)
    assert event.frictionless_join is False
