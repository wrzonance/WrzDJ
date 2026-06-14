"""Pass-1 scoring hook for DJ-curated pairings (#392).

Auto-fill/recompute lives in adjacent setbuilder work. This module is the
small contract that scorer can call when evaluating a transition candidate.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.set_pairing import SetPairing

PAIRING_SCORE_BOOST = 20.0
MAX_TRANSITION_SCORE = 100.0


@dataclass(frozen=True)
class PairingScoreResult:
    score: float
    is_dj_pairing: bool
    pairing_id: int | None
    pairing_boost: float


def load_pairing_index(db: Session, set_id: int) -> dict[tuple[str, str], SetPairing]:
    """Load saved pairings into an O(1) lookup for pass-1 candidate scoring."""
    rows = db.query(SetPairing).filter(SetPairing.set_id == set_id).all()
    return {(p.from_track_id, p.into_track_id): p for p in rows}


def apply_pairing_boost(
    from_track_id: str | None,
    into_track_id: str | None,
    base_score: float,
    pairings: dict[tuple[str, str], SetPairing],
) -> PairingScoreResult:
    """Boost a transition score by +20 when the exact saved pairing exists."""
    if not from_track_id or not into_track_id:
        return PairingScoreResult(base_score, False, None, 0.0)
    pairing = pairings.get((from_track_id, into_track_id))
    if pairing is None:
        return PairingScoreResult(base_score, False, None, 0.0)
    return PairingScoreResult(
        score=min(MAX_TRANSITION_SCORE, base_score + PAIRING_SCORE_BOOST),
        is_dj_pairing=True,
        pairing_id=pairing.id,
        pairing_boost=PAIRING_SCORE_BOOST,
    )
