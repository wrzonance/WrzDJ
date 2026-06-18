"""Play-history feedback loop for WrzDJSet (issue #403).

Derive-on-read: compare a set's planned timeline (ordered ``SetSlot`` rows,
joined to pool metadata) against the **actual** ``play_history`` for the set's
attached event, and report per-slot outcomes plus the explicit consecutive
pairing bump. There is NO schema and NO persisted outcome — every call
recomputes from live data.

Matching ladder (greedy, each play row consumed by at most one slot):
``spotify_track_id`` exact → ``dedupe_sig`` exact → fuzzy artist+title. The
fuzzy rung reuses ``track_normalizer`` and mirrors the weighting/threshold of
``now_playing.fuzzy_match_pending_request``; ``dedupe_sig`` reuses
``pool.dedupe_signature``. ``play_history`` carries NO ISRC column, so ISRC
matching is intentionally absent.

Isolation invariant (non-negotiable): this module is **read-only** on
``play_history`` AND ``requests``. The ONLY write anywhere is
``SetPairing.use_count`` via :func:`apply_outcomes_to_pairings`, the explicit
DJ action.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.models.play_history import PlayHistory
from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolTrack
from app.services.setbuilder.pool import dedupe_signature
from app.services.track_normalizer import (
    fuzzy_match_score,
    normalize_artist,
    normalize_track_title,
)

# Fuzzy rung: title weighted 0.7, artist 0.3, accept at >= 0.8 — same shape as
# now_playing.fuzzy_match_pending_request so DJ-equipment metadata noise that the
# now-playing pipeline already tolerates is tolerated here too.
_FUZZY_THRESHOLD = 0.8
_TITLE_WEIGHT = 0.7
_ARTIST_WEIGHT = 0.3

_SPOTIFY_PREFIX = "spotify:"

SlotOutcome = Literal["played", "skipped", "out_of_order", "substituted"]


@dataclass(frozen=True)
class SlotFeedback:
    """One planned slot's planned-vs-actual outcome."""

    slot_id: int
    position: int
    track_id: str | None
    title: str | None
    artist: str | None
    outcome: SlotOutcome
    play_order: int | None = None
    played_at: datetime | None = None
    deck: str | None = None


@dataclass(frozen=True)
class UnplannedPlay:
    """A play row that matched no planned slot (the DJ substituted it)."""

    play_order: int
    title: str
    artist: str
    played_at: datetime | None = None
    deck: str | None = None
    outcome: SlotOutcome = "substituted"


@dataclass(frozen=True)
class ReportSummary:
    """Headline counts for the report header."""

    total_planned: int
    total_played: int
    played: int
    skipped: int
    out_of_order: int
    unplanned: int


@dataclass(frozen=True)
class FeedbackReport:
    """Full planned-vs-actual report (slots in position order)."""

    event_id: int
    slots: list[SlotFeedback]
    unplanned: list[UnplannedPlay]
    summary: ReportSummary


@dataclass(frozen=True)
class _PlannedSlot:
    """Internal: a planned slot resolved to its pool-track identity."""

    slot: SetSlot
    track: SetPoolTrack | None

    @property
    def spotify_id(self) -> str | None:
        tid = self.track.track_id if self.track else None
        if tid and tid.startswith(_SPOTIFY_PREFIX):
            return tid[len(_SPOTIFY_PREFIX) :]
        return None

    @property
    def title(self) -> str | None:
        return self.track.title if self.track else None

    @property
    def artist(self) -> str | None:
        return self.track.artist if self.track else None

    @property
    def dedupe_sig(self) -> str | None:
        return self.track.dedupe_sig if self.track else None


class FeedbackUnavailable(ValueError):
    """Raised when a report is requested for a set with no attached event."""


def _resolve_planned_slots(set_obj: Set) -> list[_PlannedSlot]:
    """Ordered planned slots (those with a track_id) joined to pool metadata.

    Resolves a slot to its pool track by the same conventions the timeline uses:
    direct namespaced ``track_id`` (e.g. ``"tidal:1"``) or the ``"pool:{id}"``
    reference. Slots with no ``track_id`` are placeholders, not planned tracks,
    and are excluded.
    """
    by_track_id: dict[str, SetPoolTrack] = {}
    by_pool_ref: dict[str, SetPoolTrack] = {}
    for pt in set_obj.pool_tracks:
        if pt.track_id:
            by_track_id[pt.track_id] = pt
        by_pool_ref[f"pool:{pt.id}"] = pt

    planned: list[_PlannedSlot] = []
    for slot in sorted(set_obj.slots, key=lambda s: s.position):
        if not slot.track_id:
            continue
        track = by_track_id.get(slot.track_id) or by_pool_ref.get(slot.track_id)
        planned.append(_PlannedSlot(slot=slot, track=track))
    return planned


def _match_rank(planned: _PlannedSlot, play: PlayHistory) -> tuple[int, float] | None:
    """Best matching tier for (slot, play): lower tier wins, higher score breaks ties.

    Tier 0 = spotify_track_id exact, 1 = dedupe_sig exact, 2 = fuzzy artist+title.
    Returns None when the play does not match the slot at all.
    """
    if planned.spotify_id and play.spotify_track_id and planned.spotify_id == play.spotify_track_id:
        return (0, 1.0)
    if planned.dedupe_sig and planned.dedupe_sig == dedupe_signature(play.artist, play.title):
        return (1, 1.0)
    if planned.title is None or planned.artist is None:
        return None
    title_score = fuzzy_match_score(
        normalize_track_title(planned.title), normalize_track_title(play.title)
    )
    artist_score = fuzzy_match_score(
        normalize_artist(planned.artist), normalize_artist(play.artist)
    )
    combined = title_score * _TITLE_WEIGHT + artist_score * _ARTIST_WEIGHT
    if combined >= _FUZZY_THRESHOLD:
        return (2, combined)
    return None


def _match_slots_to_plays(
    planned: list[_PlannedSlot], plays: list[PlayHistory]
) -> dict[int, PlayHistory]:
    """Greedy slot→play matching. Returns {planned index → play}; plays consumed once."""
    consumed: set[int] = set()
    matches: dict[int, PlayHistory] = {}
    for idx, p in enumerate(planned):
        best: tuple[int, float, PlayHistory] | None = None
        for play in plays:
            if play.id in consumed:
                continue
            rank = _match_rank(p, play)
            if rank is None:
                continue
            tier, score = rank
            if best is None or (tier, -score) < (best[0], -best[1]):
                best = (tier, score, play)
        if best is not None:
            matches[idx] = best[2]
            consumed.add(best[2].id)
    return matches


def _out_of_order_indices(planned: list[_PlannedSlot], matches: dict[int, PlayHistory]) -> set[int]:
    """Planned indices whose play_order rank differs from their position rank.

    ``planned`` is already in position order, so iterating matched indices
    ascending yields position rank; ranking the same set by play_order yields
    the actual rank. A mismatch means the track played out of planned order.
    """
    matched_indices = sorted(matches)  # ascending = planned/position order
    by_play_order = sorted(matched_indices, key=lambda i: matches[i].play_order)
    play_rank = {idx: rank for rank, idx in enumerate(by_play_order)}
    return {
        idx for position_rank, idx in enumerate(matched_indices) if play_rank[idx] != position_rank
    }


def build_feedback_report(db: Session, set_obj: Set) -> FeedbackReport:
    """Build the planned-vs-actual report for ``set_obj`` (read-only).

    Raises :class:`FeedbackUnavailable` if the set has no attached event.
    """
    if set_obj.event_id is None:
        raise FeedbackUnavailable("Set has no attached event")

    plays = (
        db.query(PlayHistory)
        .filter(PlayHistory.event_id == set_obj.event_id)
        .order_by(PlayHistory.play_order)
        .all()
    )
    planned = _resolve_planned_slots(set_obj)
    matches = _match_slots_to_plays(planned, plays)
    out_of_order = _out_of_order_indices(planned, matches)

    slots: list[SlotFeedback] = []
    played = skipped = out_of_order_count = 0
    for idx, p in enumerate(planned):
        play = matches.get(idx)
        if play is None:
            outcome: SlotOutcome = "skipped"
            skipped += 1
        elif idx in out_of_order:
            outcome = "out_of_order"
            out_of_order_count += 1
        else:
            outcome = "played"
            played += 1
        slots.append(
            SlotFeedback(
                slot_id=p.slot.id,
                position=p.slot.position,
                track_id=p.slot.track_id,
                title=p.title,
                artist=p.artist,
                outcome=outcome,
                play_order=play.play_order if play else None,
                played_at=play.started_at if play else None,
                deck=play.deck if play else None,
            )
        )

    consumed = {play.id for play in matches.values()}
    unplanned = [
        UnplannedPlay(
            play_order=play.play_order,
            title=play.title,
            artist=play.artist,
            played_at=play.started_at,
            deck=play.deck,
        )
        for play in plays
        if play.id not in consumed
    ]

    summary = ReportSummary(
        total_planned=len(planned),
        total_played=len(plays),
        played=played + out_of_order_count,
        skipped=skipped,
        out_of_order=out_of_order_count,
        unplanned=len(unplanned),
    )
    return FeedbackReport(
        event_id=set_obj.event_id, slots=slots, unplanned=unplanned, summary=summary
    )


def apply_outcomes_to_pairings(db: Session, set_obj: Set, report: FeedbackReport) -> int:
    """Bump ``SetPairing.use_count`` for transitions that actually happened live.

    A pairing is bumped (once) when its ``from_track_id``/``into_track_id`` were
    matched to plays at **adjacent** ``play_order`` (``b == a + 1``) — i.e. the
    curated transition was performed back-to-back with nothing in between.
    Returns the number of distinct pairings bumped. This is the ONLY write in
    this module; ``play_history`` and ``requests`` are never touched.
    """
    matched = sorted(
        (s for s in report.slots if s.play_order is not None and s.track_id),
        key=lambda s: s.play_order,
    )
    pairings_by_pair = {(p.from_track_id, p.into_track_id): p for p in set_obj.pairings}
    bumped: set[int] = set()
    for a, b in zip(matched, matched[1:]):
        if b.play_order != a.play_order + 1:
            continue
        pairing = pairings_by_pair.get((a.track_id, b.track_id))
        if pairing is not None and pairing.id not in bumped:
            pairing.use_count += 1
            bumped.add(pairing.id)
    if bumped:
        db.commit()
    return len(bumped)
