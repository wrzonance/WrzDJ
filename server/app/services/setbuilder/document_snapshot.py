"""Restorable WrzDJSet document snapshots for history/autosave (issue #395)."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetCurvePoint, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.schemas.setbuilder import (
    SetDocumentCurvePoint,
    SetDocumentPool,
    SetDocumentPoolSource,
    SetDocumentPoolTrack,
    SetDocumentSettings,
    SetDocumentSlot,
    SetDocumentSnapshot,
)


def build_snapshot(set_obj: Set) -> SetDocumentSnapshot:
    """Read the current persisted builder document into a restorable snapshot."""
    return SetDocumentSnapshot(
        settings=SetDocumentSettings(
            vibe_theme=set_obj.vibe_theme,
            target_duration_sec=set_obj.target_duration_sec,
            bpm_floor=set_obj.bpm_floor,
            bpm_ceiling=set_obj.bpm_ceiling,
            key_strictness=set_obj.key_strictness,
        ),
        slots=[
            SetDocumentSlot(
                id=slot.id,
                position=slot.position,
                track_id=slot.track_id,
                locked=slot.locked,
                notes=slot.notes,
                transition_score=slot.transition_score,
                transition_warnings=slot.transition_warnings,
                target_energy=slot.target_energy,
            )
            for slot in sorted(set_obj.slots, key=lambda s: (s.position, s.id))
        ],
        curve_points=[
            SetDocumentCurvePoint(
                id=point.id,
                position_sec=point.position_sec,
                energy=point.energy,
                label=point.label,
                is_slow_window_start=point.is_slow_window_start,
                is_slow_window_end=point.is_slow_window_end,
            )
            for point in sorted(set_obj.curve_points, key=lambda p: p.id)
        ],
        pool=SetDocumentPool(
            sources=[
                SetDocumentPoolSource(
                    id=source.id,
                    kind=source.kind,
                    external_ref=source.external_ref,
                    label=source.label,
                    meta=source.meta,
                    created_at=source.created_at,
                )
                for source in sorted(set_obj.pool_sources, key=lambda s: s.id)
            ],
            tracks=[
                SetDocumentPoolTrack(
                    id=track.id,
                    source_id=track.source_id,
                    track_id=track.track_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    genre=track.genre,
                    bpm=track.bpm,
                    key=track.key,
                    camelot=track.camelot,
                    energy=track.energy,
                    isrc=track.isrc,
                    duration_sec=track.duration_sec,
                    artwork_url=track.artwork_url,
                    dedupe_sig=track.dedupe_sig,
                    created_at=track.created_at,
                )
                for track in sorted(set_obj.pool_tracks, key=lambda t: t.id)
            ],
        ),
    )


def restore_snapshot(
    db: Session, set_obj: Set, snapshot: SetDocumentSnapshot
) -> SetDocumentSnapshot:
    """Replace restorable document rows with the snapshot and return the stored state."""
    set_obj.vibe_theme = snapshot.settings.vibe_theme
    set_obj.target_duration_sec = snapshot.settings.target_duration_sec
    set_obj.bpm_floor = snapshot.settings.bpm_floor
    set_obj.bpm_ceiling = snapshot.settings.bpm_ceiling
    set_obj.key_strictness = snapshot.settings.key_strictness

    db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).delete(
        synchronize_session=False
    )
    db.query(SetPoolSource).filter(SetPoolSource.set_id == set_obj.id).delete(
        synchronize_session=False
    )
    db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).delete(synchronize_session=False)
    db.query(SetCurvePoint).filter(SetCurvePoint.set_id == set_obj.id).delete(
        synchronize_session=False
    )

    for source in snapshot.pool.sources:
        db.add(
            SetPoolSource(
                id=source.id,
                set_id=set_obj.id,
                kind=source.kind,
                external_ref=source.external_ref,
                label=source.label,
                meta=source.meta,
                created_at=source.created_at,
            )
        )
    db.flush()

    for track in snapshot.pool.tracks:
        db.add(
            SetPoolTrack(
                id=track.id,
                set_id=set_obj.id,
                source_id=track.source_id,
                track_id=track.track_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                genre=track.genre,
                bpm=track.bpm,
                key=track.key,
                camelot=track.camelot,
                energy=track.energy,
                isrc=track.isrc,
                duration_sec=track.duration_sec,
                artwork_url=track.artwork_url,
                dedupe_sig=track.dedupe_sig,
                created_at=track.created_at,
            )
        )

    for slot in snapshot.slots:
        db.add(
            SetSlot(
                id=slot.id,
                set_id=set_obj.id,
                position=slot.position,
                track_id=slot.track_id,
                locked=slot.locked,
                notes=slot.notes,
                transition_score=slot.transition_score,
                transition_warnings=slot.transition_warnings,
                target_energy=slot.target_energy,
            )
        )

    for point in snapshot.curve_points:
        db.add(
            SetCurvePoint(
                id=point.id,
                set_id=set_obj.id,
                position_sec=point.position_sec,
                energy=point.energy,
                label=point.label,
                is_slow_window_start=point.is_slow_window_start,
                is_slow_window_end=point.is_slow_window_end,
            )
        )

    db.commit()
    db.refresh(set_obj)
    return build_snapshot(set_obj)
