"""Regression tests: pass-1 must score on track GENRE continuity (#545).

Before #545 the deterministic builder ignored ``genre`` entirely —
``_track_meta`` never mapped it onto ``TrackMeta`` and ``_candidate_score`` had
no genre term — so the contract guarantee that every pool track carries a genre
was wasted. These tests seed otherwise-identical candidates that differ ONLY in
genre relative to the running context and assert the genre-continuity term now
orders them, while missing-genre tracks still degrade neutrally.
"""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.pass1_deterministic import (
    TrackMeta,
    _genre_continuity,
    _track_meta,
    build_set,
)


def _mk_set(db: Session, user: User, *, duration: int) -> Set:
    set_obj = Set(owner_id=user.id, name="Genre-driven", target_duration_sec=duration)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _mk_source(db: Session, set_obj: Set) -> SetPoolSource:
    src = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _mk_track(db: Session, set_obj: Set, source: SetPoolSource, idx: int, **kw) -> SetPoolTrack:
    """Pool track that carries a genre — bpm/key identical so genre is the only
    differentiator unless overridden."""
    defaults = dict(
        set_id=set_obj.id,
        source_id=source.id,
        track_id=f"tidal:{idx}",
        title=f"Track {idx}",
        artist=f"Artist {idx}",
        bpm=124.0,
        key="8A",
        camelot="8A",
        energy=5,
        genre="House",
        duration_sec=210,
        dedupe_sig=f"sig-{idx}",
    )
    defaults.update(kw)
    track = SetPoolTrack(**defaults)
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def test_genre_flows_into_track_meta(db: Session, test_user: User):
    """``_track_meta`` maps the pool row's genre onto ``TrackMeta.genre``."""
    set_obj = _mk_set(db, test_user, duration=210)
    src = _mk_source(db, set_obj)
    track = _mk_track(db, set_obj, src, 0, genre="Tech House")

    meta = _track_meta(track)

    assert meta.genre == "Tech House"


def test_genre_continuity_rewards_same_family_over_unrelated():
    """Same-family genres score higher continuity than unrelated ones, and a
    missing genre on either side degrades to the neutral 0.5 (no penalty).

    Pure in-memory unit test over ``TrackMeta`` — no DB / user fixtures needed.
    """
    house = TrackMeta(0, "a", "A", "Art", 124.0, "8A", 5, genre="Deep House")
    tech_house = TrackMeta(1, "b", "B", "Art", 124.0, "8A", 5, genre="Tech House")
    country = TrackMeta(2, "c", "C", "Art", 124.0, "8A", 5, genre="Country")
    no_genre = TrackMeta(3, "d", "D", "Art", 124.0, "8A", 5, genre=None)

    # No previous track => neutral, like the other *_continuity helpers.
    assert _genre_continuity(None, house) == 0.5
    # Same family (both "house") outscores an unrelated family.
    assert _genre_continuity(house, tech_house) > _genre_continuity(house, country)
    # Missing genre on either side is neutral, never a penalty.
    assert _genre_continuity(house, no_genre) == 0.5
    assert _genre_continuity(no_genre, house) == 0.5


def test_genre_continuity_treats_whitespace_only_genre_as_missing():
    """Regression for the genre-continuity term (#545): a whitespace-only genre
    is effectively missing and must degrade to the neutral 0.5 — never falsely
    perfect-match another blank (1.0) nor get penalized against a real genre
    (0.0). The pool import stores ``genre`` verbatim, so ``"   "`` is reachable.
    """
    house = TrackMeta(0, "a", "A", "Art", 124.0, "8A", 5, genre="House")
    blank = TrackMeta(1, "b", "B", "Art", 124.0, "8A", 5, genre="   ")
    other_blank = TrackMeta(2, "c", "C", "Art", 124.0, "8A", 5, genre="\t ")

    # Blank current vs real previous: not penalized to 0.0.
    assert _genre_continuity(house, blank) == 0.5
    # Real current vs blank previous: not penalized to 0.0.
    assert _genre_continuity(blank, house) == 0.5
    # Two blanks: not a false perfect match (1.0).
    assert _genre_continuity(blank, other_blank) == 0.5


def test_genre_continuity_breaks_tie_toward_matching_genre(db: Session, test_user: User):
    """Two otherwise-identical candidates compete for slot 1, following a locked
    House track at slot 0. The candidate whose genre stays in the House family
    must win — even though it has the HIGHER pool_id, which the deterministic
    ``-pool_id`` tie-break would otherwise reject.

    Before #545 genre was ignored, so both candidates scored identically and the
    LOWER-pool_id (unrelated-genre) track would win. This makes it a true
    regression test that would have failed before the fix.
    """
    # 410s target → exactly two overlap-aware slots over 210s tracks (#538): one
    # locked anchor + the contested slot 1, isolating the genre tie-break.
    set_obj = _mk_set(db, test_user, duration=410)
    src = _mk_source(db, set_obj)

    # Slot 0 is locked to a House track so the running genre context is "House".
    anchor = _mk_track(db, set_obj, src, 0, track_id="tidal:anchor", genre="House")
    # Lower pool_id = the UNRELATED-genre candidate (would win the -pool_id tie).
    far = _mk_track(db, set_obj, src, 1, track_id="tidal:country", genre="Country")
    near = _mk_track(db, set_obj, src, 2, track_id="tidal:techhouse", genre="Tech House")
    assert far.id < near.id

    db.add(SetSlot(set_id=set_obj.id, position=0, track_id=anchor.track_id, locked=True))
    db.commit()

    result = build_set(db, set_obj)

    assert result.slot_count == 2
    assert result.slots[1].track_id == "tidal:techhouse"


def test_missing_genre_pool_builds_without_penalty(db: Session, test_user: User):
    """A full pool with zero genre data still builds a set and does not crash:
    the genre term collapses to its neutral constant everywhere."""
    set_obj = _mk_set(db, test_user, duration=210 * 4)
    src = _mk_source(db, set_obj)
    for idx in range(6):
        _mk_track(db, set_obj, src, idx, genre=None)

    result = build_set(db, set_obj)

    assert result.slot_count >= 1
    assert all(s.track_id for s in result.slots)
