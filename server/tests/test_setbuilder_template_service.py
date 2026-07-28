"""Service tests for services/setbuilder/set_templates.py (#407).

Pins the invariants from the design spec: extract_template/instantiate_template
never raise on empty inputs, ownership scoping is enforced, track assignments
are stripped on extract and never resurface on instantiate, and a full
extract -> instantiate round-trip preserves every target/slot/curve field.
"""

from app.models.set import Set, SetCurvePoint, SetSlot
from app.services.setbuilder import set_templates


def _mk_set(db, owner_id, **overrides):
    defaults = dict(
        name="Warehouse Set",
        vibe_theme="Peak Time",
        target_duration_sec=3600,
        avg_transition_overlap_sec=12,
        bpm_floor=122,
        bpm_ceiling=128,
        key_strictness=0.5,
    )
    defaults.update(overrides)
    set_obj = Set(owner_id=owner_id, **defaults)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _add_slot(db, set_obj, **overrides):
    defaults = dict(
        position=0,
        track_id=None,
        locked=False,
        notes=None,
        transition_score=None,
        transition_warnings=None,
        target_energy=None,
    )
    defaults.update(overrides)
    slot = SetSlot(set_id=set_obj.id, **defaults)
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def _add_curve_point(db, set_obj, **overrides):
    defaults = dict(
        position_sec=0,
        energy=5,
        label=None,
        is_slow_window_start=False,
        is_slow_window_end=False,
    )
    defaults.update(overrides)
    point = SetCurvePoint(set_id=set_obj.id, **defaults)
    db.add(point)
    db.commit()
    db.refresh(point)
    return point


# ---------------------------------------------------------------------------
# extract_template
# ---------------------------------------------------------------------------


def test_extract_template_owned_by_user_and_never_raises_on_empty_set(db, test_user):
    empty_set = _mk_set(db, test_user.id)

    tpl = set_templates.extract_template(db, empty_set, test_user.id, "My Template")

    assert tpl.id is not None
    assert tpl.user_id == test_user.id
    assert tpl.name == "My Template"


def test_extract_template_owned_by_user_id_param_not_src_set_owner(db, test_user, admin_user):
    """extract_template must attribute the new template to the ``user_id``
    argument, never implicitly to ``src_set.owner_id`` — regression guard
    for a plausible ``SetTemplate(user_id=src_set.owner_id, ...)`` slip
    (the function receives both a ``Set`` with its own ``.owner_id`` and a
    separate ``user_id`` param).
    """
    src = _mk_set(db, admin_user.id)

    tpl = set_templates.extract_template(db, src, test_user.id, "Borrowed")

    assert tpl.user_id == test_user.id
    assert tpl.user_id != src.owner_id


def test_extract_template_preserves_slot_fields_and_strips_track_data(db, test_user):
    src = _mk_set(db, test_user.id)
    _add_slot(
        db,
        src,
        position=2,
        track_id="tidal:123",
        locked=True,
        notes="Opener",
        transition_score=0.9,
        transition_warnings='["clash"]',
        target_energy=7.5,
    )

    tpl = set_templates.extract_template(db, src, test_user.id, "Extracted")

    slots = set_templates.decode_slots(tpl.slots_json)
    assert len(slots) == 1
    slot = slots[0]
    assert slot["position"] == 2
    assert slot["locked"] is True
    assert slot["notes"] == "Opener"
    assert slot["target_energy"] == 7.5
    assert "track_id" not in slot
    assert "transition_score" not in slot
    assert "transition_warnings" not in slot


def test_extract_template_copies_target_settings_and_curve_points(db, test_user):
    src = _mk_set(db, test_user.id)
    _add_curve_point(
        db,
        src,
        position_sec=30,
        energy=8,
        label="Peak",
        is_slow_window_start=True,
        is_slow_window_end=False,
    )

    tpl = set_templates.extract_template(db, src, test_user.id, "Extracted")

    assert tpl.vibe_theme == src.vibe_theme
    assert tpl.target_duration_sec == src.target_duration_sec
    assert tpl.avg_transition_overlap_sec == src.avg_transition_overlap_sec
    assert tpl.bpm_floor == src.bpm_floor
    assert tpl.bpm_ceiling == src.bpm_ceiling
    assert tpl.key_strictness == src.key_strictness

    points = set_templates.decode_curve_points(tpl.curve_points_json)
    assert points == [
        {
            "position_sec": 30,
            "energy": 8,
            "label": "Peak",
            "is_slow_window_start": True,
            "is_slow_window_end": False,
        }
    ]


# ---------------------------------------------------------------------------
# instantiate_template
# ---------------------------------------------------------------------------


def test_instantiate_template_creates_draft_private_set_owned_by_caller(db, test_user):
    src = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, src, test_user.id, "Extracted")

    new_set = set_templates.instantiate_template(db, tpl, test_user.id, None, None)

    assert new_set.id is not None
    assert new_set.owner_id == test_user.id
    assert new_set.status == "draft"
    assert new_set.sharing_mode == "private"


def test_instantiate_template_owned_by_owner_id_param_not_template_user(db, test_user, admin_user):
    """instantiate_template must attribute the new Set to the ``owner_id``
    argument, never implicitly to ``tpl.user_id`` — regression guard for a
    plausible ``Set(owner_id=tpl.user_id, ...)`` slip.
    """
    src = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, src, test_user.id, "Extracted")

    new_set = set_templates.instantiate_template(db, tpl, admin_user.id, None, None)

    assert new_set.owner_id == admin_user.id
    assert new_set.owner_id != tpl.user_id


def test_instantiate_template_never_raises_on_empty_template(db, test_user):
    empty_set = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, empty_set, test_user.id, "Empty")

    new_set = set_templates.instantiate_template(db, tpl, test_user.id, None, None)

    assert new_set.id is not None
    assert list(new_set.slots) == []
    assert list(new_set.curve_points) == []


def test_instantiate_template_slots_always_have_null_track_id(db, test_user):
    src = _mk_set(db, test_user.id)
    _add_slot(db, src, position=0, track_id="tidal:should-not-survive")
    _add_slot(db, src, position=1, track_id="tidal:also-should-not-survive")
    tpl = set_templates.extract_template(db, src, test_user.id, "Extracted")

    new_set = set_templates.instantiate_template(db, tpl, test_user.id, None, None)

    assert len(new_set.slots) == 2
    assert all(slot.track_id is None for slot in new_set.slots)


def test_instantiate_template_name_falls_back_to_template_name_when_blank(db, test_user):
    src = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, src, test_user.id, "Fallback Name")

    new_set = set_templates.instantiate_template(db, tpl, test_user.id, None, None)
    assert new_set.name == "Fallback Name"

    new_set_2 = set_templates.instantiate_template(db, tpl, test_user.id, "  ", None)
    assert new_set_2.name == "Fallback Name"


def test_instantiate_template_uses_explicit_name_and_event_id(db, test_user, test_event):
    src = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, src, test_user.id, "Base")

    new_set = set_templates.instantiate_template(
        db, tpl, test_user.id, "Custom Name", test_event.id
    )

    assert new_set.name == "Custom Name"
    assert new_set.event_id == test_event.id


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_instantiated_slots_are_never_locked_even_when_source_was(db, test_user):
    """A locked slot means "keep the track I pinned here". Templates strip
    every ``track_id``, so carrying ``locked`` through would produce a locked
    EMPTY slot — and ``pass1_deterministic`` only refills slots where
    ``locked == False``, keeping locked ones verbatim. Such a slot is a hole
    no build can ever fill, so instantiation must always unlock.
    """
    src = _mk_set(db, test_user.id)
    _add_slot(db, src, position=0, track_id="tidal:1", locked=True, target_energy=4.0)
    _add_slot(db, src, position=1, track_id="tidal:2", locked=True, target_energy=6.0)

    tpl = set_templates.extract_template(db, src, test_user.id, "All Locked")
    new_set = set_templates.instantiate_template(db, tpl, test_user.id, None, None)

    assert [s.locked for s in src.slots] == [True, True]
    assert new_set.slots, "instantiation must still create the slots"
    assert all(s.locked is False for s in new_set.slots)
    assert all(s.track_id is None for s in new_set.slots)
    # The stored template still records the source shape.
    assert all(s["locked"] is True for s in set_templates.decode_slots(tpl.slots_json))


def test_round_trip_preserves_targets_slots_and_curve_points_bit_for_bit(db, test_user):
    src = _mk_set(db, test_user.id)
    _add_slot(
        db,
        src,
        position=0,
        track_id="tidal:1",
        locked=True,
        notes="Opener",
        transition_score=0.5,
        transition_warnings="[]",
        target_energy=3.0,
    )
    _add_slot(
        db,
        src,
        position=1,
        track_id="tidal:2",
        locked=False,
        notes=None,
        target_energy=None,
    )
    _add_curve_point(db, src, position_sec=0, energy=3, label="Start", is_slow_window_start=False)
    _add_curve_point(
        db,
        src,
        position_sec=120,
        energy=9,
        label="Peak",
        is_slow_window_end=True,
    )

    tpl = set_templates.extract_template(db, src, test_user.id, "Round Trip")
    new_set = set_templates.instantiate_template(db, tpl, test_user.id, None, None)

    assert new_set.vibe_theme == src.vibe_theme
    assert new_set.target_duration_sec == src.target_duration_sec
    assert new_set.avg_transition_overlap_sec == src.avg_transition_overlap_sec
    assert new_set.bpm_floor == src.bpm_floor
    assert new_set.bpm_ceiling == src.bpm_ceiling
    assert new_set.key_strictness == src.key_strictness

    src_slots = sorted(src.slots, key=lambda s: s.position)
    new_slots = sorted(new_set.slots, key=lambda s: s.position)
    assert len(new_slots) == len(src_slots)
    for src_slot, new_slot in zip(src_slots, new_slots):
        assert new_slot.position == src_slot.position
        assert new_slot.notes == src_slot.notes
        assert new_slot.target_energy == src_slot.target_energy
        assert new_slot.track_id is None
        # `locked` is deliberately NOT round-tripped — see
        # test_instantiated_slots_are_never_locked_even_when_source_was.
        assert new_slot.locked is False

    src_points = sorted(src.curve_points, key=lambda p: p.position_sec)
    new_points = sorted(new_set.curve_points, key=lambda p: p.position_sec)
    assert len(new_points) == len(src_points)
    for src_point, new_point in zip(src_points, new_points):
        assert new_point.position_sec == src_point.position_sec
        assert new_point.energy == src_point.energy
        assert new_point.label == src_point.label
        assert new_point.is_slow_window_start == src_point.is_slow_window_start
        assert new_point.is_slow_window_end == src_point.is_slow_window_end


# ---------------------------------------------------------------------------
# get_owned_template / list_templates / delete_template
# ---------------------------------------------------------------------------


def test_get_owned_template_scoped_to_owner(db, test_user, admin_user):
    src = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, src, test_user.id, "Mine")

    assert set_templates.get_owned_template(db, tpl.id, test_user.id) is not None
    assert set_templates.get_owned_template(db, tpl.id, admin_user.id) is None
    assert set_templates.get_owned_template(db, -1, test_user.id) is None


def test_list_templates_scoped_to_owner_newest_first(db, test_user, admin_user):
    src = _mk_set(db, test_user.id)
    other_src = _mk_set(db, admin_user.id)
    set_templates.extract_template(db, src, test_user.id, "First")
    second = set_templates.extract_template(db, src, test_user.id, "Second")
    set_templates.extract_template(db, other_src, admin_user.id, "Not mine")

    templates = set_templates.list_templates(db, test_user.id)

    assert [t.name for t in templates] == ["Second", "First"]
    assert second.id == templates[0].id


def test_delete_template_removes_row(db, test_user):
    src = _mk_set(db, test_user.id)
    tpl = set_templates.extract_template(db, src, test_user.id, "Doomed")
    tpl_id = tpl.id

    set_templates.delete_template(db, tpl)

    assert set_templates.get_owned_template(db, tpl_id, test_user.id) is None
