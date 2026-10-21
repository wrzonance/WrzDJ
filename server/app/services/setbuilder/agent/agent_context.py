"""Build authoritative set state for the SetBuilder agent context."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.agent.agent_common import _ordered_slots, _pool_tracks
from app.services.setbuilder.taste_profile import build_taste_profile, profile_context
from app.services.setbuilder.track_metadata import build_track_meta

logger = logging.getLogger(__name__)


def build_set_context(db: Session, set_obj: Set) -> str:
    """Serialize current set state and optional personalization for model context."""
    slots = _ordered_slots(db, set_obj.id)
    tracks = {
        build_track_meta(track).slot_track_id: track for track in _pool_tracks(db, set_obj.id)
    }
    try:
        taste_profile = build_taste_profile(db, set_obj.owner_id)
    except Exception as exc:
        if not db.is_active:
            db.rollback()
        logger.warning(
            "SetBuilder taste profile read failed for agent context: %s",
            exc,
            exc_info=True,
        )
        taste_profile = None
    rows = []
    for slot in slots:
        track = tracks.get(slot.track_id or "")
        rows.append(
            {
                "position": slot.position,
                "slot_id": slot.id,
                "locked": slot.locked,
                "target_energy": slot.target_energy,
                "transition_score": slot.transition_score,
                "track": (
                    {
                        "pool_track_id": track.id,
                        "title": track.title,
                        "artist": track.artist,
                        "bpm": track.bpm,
                        "key": track.camelot or track.key,
                        "energy": track.energy,
                    }
                    if track
                    else None
                ),
            }
        )
    return json.dumps(
        {
            "set_id": set_obj.id,
            "name": set_obj.name,
            "key_strictness": set_obj.key_strictness,
            "taste_profile": profile_context(taste_profile),
            "slots": rows,
        },
        separators=(",", ":"),
    )
