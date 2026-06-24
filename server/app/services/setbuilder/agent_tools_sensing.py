"""Read-only WrzDJSet agent tools (#442): analyze/explain transitions,
surface track vibes, summarize the set, and report pool coverage gaps.

These write to no table and return an empty affected-positions set. Dispatched
through ``apply_tool_call``'s closed allowlist like every other tool.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolTrack
from app.models.user import User
from app.services.recommendation.camelot import parse_key
from app.services.setbuilder.agent_common import (
    AgentToolError,
    _ordered_slots,
    _pool_tracks,
    _slot_or_error,
)
from app.services.setbuilder.pairing_scoring import load_pairing_index
from app.services.setbuilder.pass1_deterministic import TrackMeta, transition_score
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta
from app.services.setbuilder.vibe_resolver import TrackVibeState, build_pool_vibe_state

logger = logging.getLogger(__name__)


# The 24 Camelot-wheel slots: numbers 1-12 on each of the A (minor) and B
# (major) rings. Used by analyze_pool_gaps to report which slots the pool
# leaves uncovered.
ALL_CAMELOT_KEYS: tuple[str, ...] = tuple(
    f"{number}{letter}" for number in range(1, 13) for letter in ("A", "B")
)
# analyze_pool_gaps bins pool BPMs into fixed-width bands; a band holding
# fewer than SPARSE_BAND_THRESHOLD tracks is flagged as a coverage hole.
BPM_BAND_WIDTH = 10
SPARSE_BAND_THRESHOLD = 2


def _tool_analyze_transition(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    position = int(payload["position"])
    slots = _ordered_slots(db, set_obj.id)
    if position <= 0 or position >= len(slots):
        raise AgentToolError("position must identify a transition destination")
    tracks = {
        _pass1_track_meta(t).slot_track_id: _pass1_track_meta(t)
        for t in _pool_tracks(db, set_obj.id)
    }
    prev = tracks.get(slots[position - 1].track_id or "")
    curr = tracks.get(slots[position].track_id or "")
    if curr is None:
        raise AgentToolError("slot has no pool metadata")
    score, warnings = transition_score(prev, curr, set_obj.key_strictness)
    return {"position": position, "score": score, "warnings": warnings}, set()


def _tool_explain_transition(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only: turn a transition's terse warning codes into grounded sentences."""
    position = int(payload["position"])
    slots = _ordered_slots(db, set_obj.id)
    if position <= 0 or position >= len(slots):
        raise AgentToolError("position must identify a transition destination")
    tracks = {
        _pass1_track_meta(t).slot_track_id: _pass1_track_meta(t)
        for t in _pool_tracks(db, set_obj.id)
    }
    prev = tracks.get(slots[position - 1].track_id or "")
    curr = tracks.get(slots[position].track_id or "")
    if curr is None:
        raise AgentToolError("slot has no pool metadata")
    score, warnings = transition_score(prev, curr, set_obj.key_strictness)
    explanations = [
        {"code": code, "detail": _explain_warning(code, prev, curr)} for code in warnings
    ]
    return {
        "position": position,
        "score": score,
        "explanations": explanations,
        "prev": _track_summary(prev),
        "curr": _track_summary(curr),
    }, set()


def _track_summary(meta: TrackMeta | None) -> dict[str, Any] | None:
    """Compact prev/curr summary of the fields that drive transition scoring."""
    if meta is None:
        return None
    return {
        "title": meta.title,
        "artist": meta.artist,
        "bpm": meta.bpm,
        "key": meta.key,
        "energy": meta.energy,
    }


def _explain_warning(code: str, prev: TrackMeta | None, curr: TrackMeta) -> str:
    """Build one human-readable sentence for a warning, grounded in real fields."""
    if code == "bpm_jump":
        prev_bpm = _fmt_number(prev.bpm) if prev else "unknown"
        return (
            f"Big tempo gap: {prev_bpm} BPM into {_fmt_number(curr.bpm)} BPM — "
            "too far to ride the same groove."
        )
    if code == "key_clash":
        prev_key = prev.key if (prev and prev.key) else "unknown"
        return (
            f"Keys clash: {prev_key} into {curr.key or 'unknown'} are not "
            "harmonically adjacent on the Camelot wheel."
        )
    if code == "mood_shift":
        # Forward-looking: transition_score may emit mood_shift, but the current
        # pool→TrackMeta path never populates mood (SetPoolTrack has no mood column),
        # so this branch is defensive and only exercised directly by unit tests today.
        prev_mood = prev.mood if (prev and prev.mood) else "unknown"
        return (
            f"Mood swings from {prev_mood} to {curr.mood or 'unknown'} — "
            "the emotional energy lurches."
        )
    if code == "repeat_artist":
        artist = curr.artist or (prev.artist if prev else None) or "the same artist"
        return f"Back-to-back {artist}: repeating an artist can stall the set's variety."
    return code.replace("_", " ")


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:g}"


def _tool_get_track_vibes(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only: surface a slot track's resolved TrackVibe tags (#457).

    Resolves the slot -> its pool track -> the owner-merged vibe state via
    ``vibe_resolver``. No vibe data yields an explicit empty result, never an
    error. Writes to no table; returns ``set()`` (no affected positions).
    """
    slot = _slot_or_error(db, set_obj.id, int(payload["slot_id"]))
    owner = db.get(User, set_obj.owner_id)
    if owner is None:
        raise AgentToolError("Set owner not found")
    pool_track = _slot_pool_track(db, set_obj.id, slot.track_id)
    state = (
        build_pool_vibe_state(db, owner, set_obj, pool_track.id) if pool_track is not None else None
    )
    return _vibe_state_result(slot, pool_track, state), set()


def _slot_pool_track(db: Session, set_id: int, slot_track_id: str | None) -> SetPoolTrack | None:
    """Map a slot's namespaced track_id back to its pool track row, if any."""
    for track in _pool_tracks(db, set_id):
        if _pass1_track_meta(track).slot_track_id == (slot_track_id or ""):
            return track
    return None


def _vibe_state_result(
    slot: SetSlot, pool_track: SetPoolTrack | None, state: TrackVibeState | None
) -> dict[str, Any]:
    """Shape a TrackVibeState into the agent-facing vibe result payload."""
    resolved = state.resolved if state else None
    has_vibe = resolved is not None and (resolved.energy is not None or resolved.mood is not None)
    return {
        "slot_id": slot.id,
        "position": slot.position,
        "pool_track_id": pool_track.id if pool_track else None,
        "has_vibe": has_vibe,
        "resolved": {
            "energy": resolved.energy if resolved else None,
            "energy_source": resolved.energy_source if resolved else None,
            "mood": resolved.mood if resolved else None,
            "mood_source": resolved.mood_source if resolved else None,
        },
    }


def _tool_summarize_set(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only snapshot of the whole set: duration, BPM arc, key journey, energy.

    Returns ``(summary, set())`` — no positions are affected because nothing is
    mutated. Mirrors ``_tool_analyze_transition`` (read-only), not ``_tool``.
    """
    del payload  # no input args
    slots = _ordered_slots(db, set_obj.id)
    # One view per pool track: meta carries BPM + normalized key, the raw row
    # carries duration_sec (which TrackMeta does not expose).
    by_track_id = {
        _pass1_track_meta(t).slot_track_id: (_pass1_track_meta(t), t)
        for t in _pool_tracks(db, set_obj.id)
    }

    total_duration_sec = 0
    bpms: list[float] = []
    key_journey: list[str] = []
    energy_values: list[float | None] = []
    for slot in slots:
        meta, track = by_track_id.get(slot.track_id or "", (None, None))
        if track is not None and track.duration_sec:
            total_duration_sec += int(track.duration_sec)
        if meta is not None and meta.bpm is not None:
            bpms.append(float(meta.bpm))
        camelot = parse_key(meta.key) if meta is not None else None
        if camelot is not None:
            key_journey.append(str(camelot))
        energy_values.append(slot.target_energy)

    target_duration_sec = set_obj.target_duration_sec
    return {
        "slot_count": len(slots),
        "total_duration_sec": total_duration_sec,
        "target_duration_sec": target_duration_sec,
        "duration_delta_sec": (
            total_duration_sec - target_duration_sec if target_duration_sec is not None else None
        ),
        "bpm_arc": _bpm_arc(bpms),
        "key_journey": key_journey,
        "energy_profile": _energy_profile(energy_values),
    }, set()


def _bpm_arc(bpms: list[float]) -> dict[str, float] | None:
    """Min/max/first/last/mean over slots that have a BPM; ``None`` if none do."""
    if not bpms:
        return None
    return {
        "min": min(bpms),
        "max": max(bpms),
        "first": bpms[0],
        "last": bpms[-1],
        "mean": round(sum(bpms) / len(bpms), 1),
    }


def _energy_profile(values: list[float | None]) -> dict[str, Any]:
    """Ordered ``target_energy`` per slot plus the slot position of the peak."""
    known = [(pos, val) for pos, val in enumerate(values) if val is not None]
    peak_position = max(known, key=lambda pair: pair[1])[0] if known else None
    return {"values": values, "peak_position": peak_position}


def _tool_analyze_pool_gaps(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only coverage report over the set's pool: missing Camelot keys, BPM
    bands, and genre + energy coverage (#542).

    Genre + energy are read straight from the resolved pool rows (which #542's
    store hydration now fills), not from the previously-dead pool energy column —
    consistent with the build-gate ``coverage.pool_coverage`` field set."""
    del payload
    pool = _pool_tracks(db, set_obj.id)
    metas = [_pass1_track_meta(t) for t in pool]
    camelot_keys = [str(pos) for pos in (parse_key(m.key) for m in metas) if pos is not None]
    bpms = [float(m.bpm) for m in metas if m.bpm is not None]
    genre_count = sum(1 for t in pool if t.genre)
    energy_count = sum(1 for t in pool if t.energy is not None)
    present = set(camelot_keys)
    missing = [key for key in ALL_CAMELOT_KEYS if key not in present]
    bands = _bpm_bands(set_obj, bpms)
    logger.debug(
        "Set %s analyze_pool_gaps: pool=%d keyed=%d bpm=%d genre=%d energy=%d missing_keys=%d",
        set_obj.id,
        len(metas),
        len(camelot_keys),
        len(bpms),
        genre_count,
        energy_count,
        len(missing),
    )
    return {
        "pool_size": len(metas),
        "keyed_track_count": len(camelot_keys),
        "bpm_track_count": len(bpms),
        "genre_track_count": genre_count,
        "energy_track_count": energy_count,
        "missing_genre_count": len(metas) - genre_count,
        "missing_energy_count": len(metas) - energy_count,
        "missing_camelot_keys": missing,
        "bpm_bands": bands,
        "sparse_bands": [b for b in bands if b["count"] < SPARSE_BAND_THRESHOLD],
    }, set()


def _bpm_bands(set_obj: Set, bpms: list[float]) -> list[dict[str, Any]]:
    """Bucket pool BPMs into fixed-width bands across the set's target window.

    Bands are anchored to ``set_obj.bpm_floor``..``bpm_ceiling`` (the declared
    window) when set, else the observed pool min/max. The range is then widened
    to also cover any track outside that window, so every BPM-tagged pool track
    lands in exactly one band — ``sum(band counts) == bpm_track_count`` always
    holds, and out-of-window tracks surface as their own bands rather than
    silently vanishing. Empty bands are included so the agent sees tempo holes,
    not just where tracks cluster.
    """
    if not bpms:
        return []
    floor = set_obj.bpm_floor if set_obj.bpm_floor is not None else int(min(bpms))
    ceiling = set_obj.bpm_ceiling if set_obj.bpm_ceiling is not None else int(max(bpms))
    low = min(floor, int(min(bpms)))
    high = max(ceiling, int(max(bpms)))
    start = (low // BPM_BAND_WIDTH) * BPM_BAND_WIDTH
    bands: list[dict[str, Any]] = []
    edge = start
    while edge <= high:
        band_end = edge + BPM_BAND_WIDTH
        count = sum(1 for bpm in bpms if edge <= bpm < band_end)
        bands.append({"label": f"{edge}-{band_end}", "min": edge, "max": band_end, "count": count})
        edge = band_end
    return bands


def _tool_static_critique(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    del payload
    slots = _ordered_slots(db, set_obj.id)
    scores = [s.transition_score for s in slots[1:] if s.transition_score is not None]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    return {"average_transition_score": avg, "slot_count": len(slots)}, set()


def _tool_suggest_pairings(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only: the set's consecutive transitions with score + whether each is
    already a saved (pinned) pairing (#442).

    The score is the raw ``transition_score`` — the +20 DJ-pairing boost steers
    pass-1 candidate ordering, not an existing adjacency's stored score, so this
    reports the honest transition quality alongside an ``is_pinned`` flag and the
    endpoints' ``pool_track_id`` so the agent can act with ``add_pairing``.
    """
    del payload
    slots = _ordered_slots(db, set_obj.id)
    by_track_id = {
        _pass1_track_meta(track).slot_track_id: track for track in _pool_tracks(db, set_obj.id)
    }
    pinned = load_pairing_index(db, set_obj.id)
    transitions: list[dict[str, Any]] = []
    for position in range(1, len(slots)):
        prev_track_id = slots[position - 1].track_id or ""
        curr_track_id = slots[position].track_id or ""
        prev_track = by_track_id.get(prev_track_id)
        curr_track = by_track_id.get(curr_track_id)
        if curr_track is None:
            continue
        prev_meta = _pass1_track_meta(prev_track) if prev_track is not None else None
        score, warnings = transition_score(
            prev_meta, _pass1_track_meta(curr_track), set_obj.key_strictness
        )
        pairing = pinned.get((prev_track_id, curr_track_id))
        transitions.append(
            {
                "position": position,
                "score": score,
                "warnings": warnings,
                "is_pinned": pairing is not None,
                "pairing_id": pairing.id if pairing is not None else None,
                "from": _pairing_endpoint(prev_track),
                "into": _pairing_endpoint(curr_track),
            }
        )
    pinned_count = sum(1 for transition in transitions if transition["is_pinned"])
    return {"transitions": transitions, "pinned_count": pinned_count}, set()


def _pairing_endpoint(track: SetPoolTrack | None) -> dict[str, Any]:
    """Compact pool-track reference the agent can feed back to add_pairing."""
    if track is None:
        return {"pool_track_id": None, "title": None, "artist": None}
    return {"pool_track_id": track.id, "title": track.title, "artist": track.artist}
