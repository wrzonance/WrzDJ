"""Tests for WrzDJSet sharing + duplication (issue #398).

Service level: duplicate copies children and resets lifecycle state;
token regenerate/revoke; malformed-token short circuit.
API level: owner-scoped share/revoke/duplicate routes, public view-only
projection (no ids / owner identity leakage), auth gating.
"""

from app.models.set import Set, SetCurvePoint, SetSlot
from app.services.auth import get_password_hash
from app.services.setbuilder import share_service


def _seed_set(db, owner_id, **overrides) -> Set:
    fields = {
        "owner_id": owner_id,
        "name": "Warehouse Closer",
        "vibe_theme": "dark-techno",
        "target_duration_sec": 3600,
        "bpm_floor": 124,
        "bpm_ceiling": 132,
        "key_strictness": 0.7,
        "status": "locked",
        "tidal_playlist_id": "pl-123",
    }
    fields.update(overrides)
    set_obj = Set(**fields)
    db.add(set_obj)
    db.flush()
    db.add(
        SetSlot(
            set_id=set_obj.id,
            position=1,
            track_id="tidal:111",
            locked=True,
            notes="opener",
            transition_score=0.9,
            transition_warnings='["bpm jump"]',
        )
    )
    db.add(SetSlot(set_id=set_obj.id, position=2, track_id="tidal:222"))
    db.add(
        SetCurvePoint(
            set_id=set_obj.id,
            position_sec=0,
            energy=4,
            label="warmup",
            is_slow_window_start=True,
        )
    )
    db.add(
        SetCurvePoint(
            set_id=set_obj.id,
            position_sec=1800,
            energy=9,
            label="peak",
            is_slow_window_end=True,
        )
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _make_second_dj(db):
    from app.models.user import User

    user = User(username="otherdj", password_hash=get_password_hash("x" * 12), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, username, password):
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Service: duplicate
# ---------------------------------------------------------------------------


def test_duplicate_copies_children_and_resets_state(db, test_user):
    src = _seed_set(db, test_user.id)
    src.share_token = "A" * 43
    db.commit()

    dup = share_service.duplicate_set(db, src)

    assert dup.id != src.id
    assert dup.name == "Warehouse Closer (copy)"
    assert dup.owner_id == test_user.id
    # targets + vibe copied
    assert dup.vibe_theme == "dark-techno"
    assert dup.target_duration_sec == 3600
    assert dup.bpm_floor == 124
    assert dup.bpm_ceiling == 132
    assert dup.key_strictness == 0.7
    # lifecycle reset
    assert dup.status == "draft"
    assert dup.sharing_mode == "private"
    assert dup.share_token is None
    assert dup.tidal_playlist_id is None
    assert dup.exported_at is None
    # slots copied with all fields
    assert [(s.position, s.track_id) for s in dup.slots] == [(1, "tidal:111"), (2, "tidal:222")]
    first = next(s for s in dup.slots if s.position == 1)
    assert first.locked is True
    assert first.notes == "opener"
    assert first.transition_score == 0.9
    assert first.transition_warnings == '["bpm jump"]'
    # curve (incl. slow/vibe windows) copied
    points = sorted(dup.curve_points, key=lambda c: c.position_sec)
    assert [(c.position_sec, c.energy, c.label) for c in points] == [
        (0, 4, "warmup"),
        (1800, 9, "peak"),
    ]
    assert points[0].is_slow_window_start is True
    assert points[1].is_slow_window_end is True
    # source untouched
    db.refresh(src)
    assert src.status == "locked"
    assert len(src.slots) == 2


def test_duplicate_truncates_long_name(db, test_user):
    src = _seed_set(db, test_user.id, name="x" * 120)
    dup = share_service.duplicate_set(db, src)
    assert len(dup.name) == 120
    assert dup.name.endswith(" (copy)")


# ---------------------------------------------------------------------------
# Service: token lifecycle
# ---------------------------------------------------------------------------


def test_regenerate_changes_token(db, test_user):
    src = _seed_set(db, test_user.id)
    share_service.regenerate_share_token(db, src)
    first = src.share_token
    assert first is not None and len(first) >= 32
    share_service.regenerate_share_token(db, src)
    assert src.share_token != first


def test_revoke_nulls_token(db, test_user):
    src = _seed_set(db, test_user.id)
    share_service.regenerate_share_token(db, src)
    share_service.revoke_share_token(db, src)
    assert src.share_token is None


def test_get_by_token_rejects_bad_format(db, test_user):
    src = _seed_set(db, test_user.id)
    share_service.regenerate_share_token(db, src)
    assert share_service.get_set_by_share_token(db, src.share_token) is src
    assert share_service.get_set_by_share_token(db, "short") is None
    assert share_service.get_set_by_share_token(db, "x" * 200) is None
    assert share_service.get_set_by_share_token(db, "bad token!@#" + "a" * 20) is None
