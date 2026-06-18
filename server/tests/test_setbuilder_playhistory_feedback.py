"""Play-history feedback loop (#403) — service + API tests.

Covers the planned-vs-actual matching ladder (spotify_track_id → dedupe_sig →
fuzzy), per-slot outcomes (played / skipped / out_of_order), report-level
unplanned (substituted) plays, the explicit consecutive-pairing bump, and the
non-negotiable isolation invariant: read-only on ``play_history`` AND
``requests`` (the only write is ``SetPairing.use_count``).
"""

from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.models.play_history import PlayHistory
from app.models.request import Request, RequestStatus
from app.models.set import SetSlot
from app.models.set_pairing import SetPairing
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services.setbuilder import playhistory_feedback as feedback
from app.services.setbuilder import pool, set_service


def _mk_set(db, owner_id, event_id=None, name="Feedback Set"):
    return set_service.create_set(db, owner_id=owner_id, name=name, event_id=event_id)


def _mk_pool_track(db, set_id, track_id, title, artist):
    source = (
        db.query(SetPoolSource)
        .filter(SetPoolSource.set_id == set_id, SetPoolSource.kind == "manual")
        .one_or_none()
    )
    if source is None:
        source = SetPoolSource(set_id=set_id, kind="manual", label="Manual")
        db.add(source)
        db.flush()
    track = SetPoolTrack(
        set_id=set_id,
        source_id=source.id,
        track_id=track_id,
        title=title,
        artist=artist,
        dedupe_sig=pool.dedupe_signature(artist, title),
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def _mk_slot(db, set_id, position, track_id):
    slot = SetSlot(set_id=set_id, position=position, track_id=track_id)
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def _mk_play(db, event_id, play_order, title, artist, *, spotify_track_id=None, deck=None):
    play = PlayHistory(
        event_id=event_id,
        title=title,
        artist=artist,
        spotify_track_id=spotify_track_id,
        deck=deck,
        started_at=utcnow() + timedelta(minutes=play_order),
        play_order=play_order,
    )
    db.add(play)
    db.commit()
    db.refresh(play)
    return play


def _by_slot(report):
    return {s.slot_id: s for s in report.slots}


# ---------------------------------------------------------------------------
# Matching ladder


def test_spotify_track_id_exact_match_marks_played(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    track = _mk_pool_track(db, set_obj.id, "spotify:abc", "Strobe", "deadmau5")
    slot = _mk_slot(db, set_obj.id, 0, track.track_id)
    # Title/artist deliberately disagree so ONLY the spotify id can match.
    _mk_play(db, test_event.id, 1, "Totally Different", "Someone Else", spotify_track_id="abc")

    report = feedback.build_feedback_report(db, set_obj)

    assert _by_slot(report)[slot.id].outcome == "played"
    assert report.summary.played == 1
    assert report.unplanned == []


def test_dedupe_signature_match_marks_played(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    track = _mk_pool_track(db, set_obj.id, "tidal:1", "Strobe (Original Mix)", "deadmau5")
    slot = _mk_slot(db, set_obj.id, 0, track.track_id)
    # No spotify id; normalized title+artist hashes to the same dedupe_sig.
    _mk_play(db, test_event.id, 1, "Strobe", "Deadmau5")

    report = feedback.build_feedback_report(db, set_obj)

    assert _by_slot(report)[slot.id].outcome == "played"


def test_fuzzy_match_marks_played(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    track = _mk_pool_track(db, set_obj.id, "tidal:1", "Strobe", "deadmau5")
    slot = _mk_slot(db, set_obj.id, 0, track.track_id)
    # Typo'd title: no spotify id, dedupe_sig differs, but fuzzy clears threshold.
    _mk_play(db, test_event.id, 1, "Strobee", "deadmau5")

    report = feedback.build_feedback_report(db, set_obj)

    assert _by_slot(report)[slot.id].outcome == "played"


def test_unmatched_slot_marks_skipped(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    track = _mk_pool_track(db, set_obj.id, "tidal:1", "Strobe", "deadmau5")
    slot = _mk_slot(db, set_obj.id, 0, track.track_id)
    _mk_play(db, test_event.id, 1, "Nothing Alike", "Other Artist")

    report = feedback.build_feedback_report(db, set_obj)

    assert _by_slot(report)[slot.id].outcome == "skipped"
    assert report.summary.skipped == 1
    assert len(report.unplanned) == 1
    assert report.unplanned[0].outcome == "substituted"


def test_out_of_order_detection(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    a = _mk_pool_track(db, set_obj.id, "tidal:a", "Alpha", "AA")
    b = _mk_pool_track(db, set_obj.id, "tidal:b", "Bravo", "BB")
    c = _mk_pool_track(db, set_obj.id, "tidal:c", "Charlie", "CC")
    slot_a = _mk_slot(db, set_obj.id, 0, a.track_id)
    slot_b = _mk_slot(db, set_obj.id, 1, b.track_id)
    slot_c = _mk_slot(db, set_obj.id, 2, c.track_id)
    # Planned A,B,C; actually played A, C, B.
    _mk_play(db, test_event.id, 1, "Alpha", "AA")
    _mk_play(db, test_event.id, 2, "Charlie", "CC")
    _mk_play(db, test_event.id, 3, "Bravo", "BB")

    report = feedback.build_feedback_report(db, set_obj)
    by_slot = _by_slot(report)

    assert by_slot[slot_a.id].outcome == "played"
    assert by_slot[slot_b.id].outcome == "out_of_order"
    assert by_slot[slot_c.id].outcome == "out_of_order"
    assert report.summary.out_of_order == 2


def test_unplanned_play_surfaced_as_substituted(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    track = _mk_pool_track(db, set_obj.id, "tidal:1", "Alpha", "AA")
    _mk_slot(db, set_obj.id, 0, track.track_id)
    _mk_play(db, test_event.id, 1, "Alpha", "AA")
    _mk_play(db, test_event.id, 2, "Surprise Drop", "Guest")

    report = feedback.build_feedback_report(db, set_obj)

    assert report.summary.played == 1
    assert len(report.unplanned) == 1
    assert report.unplanned[0].title == "Surprise Drop"
    assert report.unplanned[0].play_order == 2
    assert report.summary.unplanned == 1


# ---------------------------------------------------------------------------
# Explicit apply-pairings action


def test_apply_bumps_consecutive_pairing(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    a = _mk_pool_track(db, set_obj.id, "tidal:a", "Alpha", "AA")
    b = _mk_pool_track(db, set_obj.id, "tidal:b", "Bravo", "BB")
    _mk_slot(db, set_obj.id, 0, a.track_id)
    _mk_slot(db, set_obj.id, 1, b.track_id)
    pairing = SetPairing(
        set_id=set_obj.id, from_track_id="tidal:a", into_track_id="tidal:b", use_count=0
    )
    db.add(pairing)
    db.commit()
    _mk_play(db, test_event.id, 1, "Alpha", "AA")
    _mk_play(db, test_event.id, 2, "Bravo", "BB")

    report = feedback.build_feedback_report(db, set_obj)
    bumped = feedback.apply_outcomes_to_pairings(db, set_obj, report)

    db.refresh(pairing)
    assert bumped == 1
    assert pairing.use_count == 1


def test_apply_ignores_non_consecutive_pairing(db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    a = _mk_pool_track(db, set_obj.id, "tidal:a", "Alpha", "AA")
    b = _mk_pool_track(db, set_obj.id, "tidal:b", "Bravo", "BB")
    _mk_slot(db, set_obj.id, 0, a.track_id)
    _mk_slot(db, set_obj.id, 1, b.track_id)
    pairing = SetPairing(
        set_id=set_obj.id, from_track_id="tidal:a", into_track_id="tidal:b", use_count=0
    )
    db.add(pairing)
    db.commit()
    # A then an unplanned track then B — A and B are NOT adjacent in play order.
    _mk_play(db, test_event.id, 1, "Alpha", "AA")
    _mk_play(db, test_event.id, 2, "Interlude", "Guest")
    _mk_play(db, test_event.id, 3, "Bravo", "BB")

    report = feedback.build_feedback_report(db, set_obj)
    bumped = feedback.apply_outcomes_to_pairings(db, set_obj, report)

    db.refresh(pairing)
    assert bumped == 0
    assert pairing.use_count == 0


def test_feedback_is_read_only_on_requests_and_play_history(db, test_user, test_event):
    """Isolation invariant: building + applying never mutates requests/play_history."""
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    a = _mk_pool_track(db, set_obj.id, "tidal:a", "Alpha", "AA")
    b = _mk_pool_track(db, set_obj.id, "tidal:b", "Bravo", "BB")
    _mk_slot(db, set_obj.id, 0, a.track_id)
    _mk_slot(db, set_obj.id, 1, b.track_id)
    pairing = SetPairing(
        set_id=set_obj.id, from_track_id="tidal:a", into_track_id="tidal:b", use_count=0
    )
    db.add(pairing)
    request = Request(
        event_id=test_event.id,
        song_title="Alpha",
        artist="AA",
        source="spotify",
        status=RequestStatus.NEW.value,
        dedupe_key="dk-alpha",
    )
    db.add(request)
    db.commit()
    play_a = _mk_play(db, test_event.id, 1, "Alpha", "AA")
    play_b = _mk_play(db, test_event.id, 2, "Bravo", "BB")

    report = feedback.build_feedback_report(db, set_obj)
    feedback.apply_outcomes_to_pairings(db, set_obj, report)
    db.expire_all()

    # Requests untouched (scoped to this test's row so unrelated seed data can't skew it).
    assert db.query(Request).filter(Request.id == request.id).count() == 1
    refreshed = db.get(Request, request.id)
    assert refreshed.status == RequestStatus.NEW.value
    assert refreshed.song_title == "Alpha"
    # Play history untouched (matched_request_id stays None, count unchanged).
    assert db.query(PlayHistory).filter(PlayHistory.event_id == test_event.id).count() == 2
    assert db.get(PlayHistory, play_a.id).matched_request_id is None
    assert db.get(PlayHistory, play_b.id).matched_request_id is None


# ---------------------------------------------------------------------------
# API surface


def test_build_report_rejects_set_without_event(db, test_user):
    """Service contract: a report cannot be derived without an attached event."""
    set_obj = _mk_set(db, test_user.id, event_id=None)
    with pytest.raises(feedback.FeedbackUnavailable):
        feedback.build_feedback_report(db, set_obj)


def test_get_playback_report_requires_attached_event(client, auth_headers, db, test_user):
    set_obj = _mk_set(db, test_user.id, event_id=None)
    resp = client.get(f"/api/setbuilder/sets/{set_obj.id}/playback-report", headers=auth_headers)
    assert resp.status_code == 400, resp.json()


def test_get_playback_report_unowned_returns_404(client, auth_headers, db, admin_user):
    other = _mk_set(db, admin_user.id, event_id=None)
    resp = client.get(f"/api/setbuilder/sets/{other.id}/playback-report", headers=auth_headers)
    assert resp.status_code == 404


def test_get_playback_report_shape(client, auth_headers, db, test_user, test_event):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    track = _mk_pool_track(db, set_obj.id, "tidal:a", "Alpha", "AA")
    _mk_slot(db, set_obj.id, 0, track.track_id)
    _mk_play(db, test_event.id, 1, "Alpha", "AA")
    _mk_play(db, test_event.id, 2, "Unplanned", "Guest")

    resp = client.get(f"/api/setbuilder/sets/{set_obj.id}/playback-report", headers=auth_headers)

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["event_id"] == test_event.id
    assert body["summary"]["played"] == 1
    assert len(body["slots"]) == 1
    assert body["slots"][0]["outcome"] == "played"
    assert len(body["unplanned"]) == 1
    assert body["unplanned"][0]["outcome"] == "substituted"


def test_apply_pairings_endpoint_returns_bumped_and_pairings(
    client, auth_headers, db, test_user, test_event
):
    set_obj = _mk_set(db, test_user.id, event_id=test_event.id)
    a = _mk_pool_track(db, set_obj.id, "tidal:a", "Alpha", "AA")
    b = _mk_pool_track(db, set_obj.id, "tidal:b", "Bravo", "BB")
    _mk_slot(db, set_obj.id, 0, a.track_id)
    _mk_slot(db, set_obj.id, 1, b.track_id)
    db.add(
        SetPairing(set_id=set_obj.id, from_track_id="tidal:a", into_track_id="tidal:b", use_count=0)
    )
    db.commit()
    _mk_play(db, test_event.id, 1, "Alpha", "AA")
    _mk_play(db, test_event.id, 2, "Bravo", "BB")

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/playback-report/apply-pairings", headers=auth_headers
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["bumped"] == 1
    assert body["pairings"]["pairings"][0]["use_count"] == 1


def test_apply_pairings_requires_attached_event(client, auth_headers, db, test_user):
    set_obj = _mk_set(db, test_user.id, event_id=None)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/playback-report/apply-pairings", headers=auth_headers
    )
    assert resp.status_code == 400
