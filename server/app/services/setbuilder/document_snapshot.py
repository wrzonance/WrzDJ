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
from app.services.setbuilder import pool


def _current_pool_track_metadata(
    db: Session, set_id: int
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    """Snapshot server-owned enrichment fields before destructive restore."""
    by_track_id: dict[str, dict[str, object]] = {}
    by_dedupe_sig: dict[str, dict[str, object]] = {}
    current_tracks = (
        db.query(
            SetPoolTrack.track_id,
            SetPoolTrack.dedupe_sig,
            SetPoolTrack.bpm,
            SetPoolTrack.key,
            SetPoolTrack.camelot,
            SetPoolTrack.genre,
            SetPoolTrack.duration_sec,
            SetPoolTrack.enrichment_status,
        )
        .filter(SetPoolTrack.set_id == set_id)
        .order_by(SetPoolTrack.id)
        .all()
    )
    for (
        track_id,
        dedupe_sig,
        bpm,
        key,
        camelot,
        genre,
        duration_sec,
        enrichment_status,
    ) in current_tracks:
        metadata = {
            "bpm": bpm,
            "key": key,
            "camelot": camelot,
            "genre": genre,
            "duration_sec": duration_sec,
            "enrichment_status": enrichment_status,
        }
        if track_id:
            by_track_id.setdefault(track_id, metadata)
        by_dedupe_sig.setdefault(dedupe_sig, metadata)
    return by_track_id, by_dedupe_sig


def _matched_current_metadata(
    track: SetDocumentPoolTrack,
    by_track_id: dict[str, dict[str, object]],
    by_dedupe_sig: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    if track.track_id:
        match = by_track_id.get(track.track_id)
        if match is not None:
            return match
    return by_dedupe_sig.get(track.dedupe_sig)


def _current_or_snapshot(
    metadata: dict[str, object] | None, field: str, snapshot_value: object
) -> object:
    if metadata is None:
        return snapshot_value
    current_value = metadata[field]
    return current_value if current_value is not None else snapshot_value


def _merged_enrichment_status(
    metadata: dict[str, object] | None,
    *,
    bpm: object,
    key: object,
    genre: object,
    duration_sec: object,
) -> str:
    if metadata is not None and metadata["enrichment_status"] != pool.POOL_ENRICH_PENDING:
        return str(metadata["enrichment_status"])
    return pool.terminal_enrichment_status(
        bpm=bpm,
        key=key,
        genre=genre,
        duration_sec=duration_sec,
    )


def _remap_synthetic_pool_track_id(track_id: str | None, id_map: dict[int, int]) -> str | None:
    if not track_id or not track_id.startswith("pool:"):
        return track_id
    raw_id = track_id.removeprefix("pool:")
    if not raw_id.isdigit():
        return track_id
    restored_id = id_map.get(int(raw_id))
    return f"pool:{restored_id}" if restored_id is not None else track_id


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
                    enrichment_status=track.enrichment_status,
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

    current_by_track_id, current_by_dedupe_sig = _current_pool_track_metadata(db, set_obj.id)

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

    source_id_map: dict[int, int] = {}
    for source in snapshot.pool.sources:
        restored_source = SetPoolSource(
            set_id=set_obj.id,
            kind=source.kind,
            external_ref=source.external_ref,
            label=source.label,
            meta=source.meta,
            created_at=source.created_at,
        )
        db.add(restored_source)
        db.flush()
        source_id_map[source.id] = restored_source.id

    pool_track_id_map: dict[int, int] = {}
    for track in snapshot.pool.tracks:
        current_metadata = _matched_current_metadata(
            track, current_by_track_id, current_by_dedupe_sig
        )
        bpm = _current_or_snapshot(current_metadata, "bpm", track.bpm)
        key = _current_or_snapshot(current_metadata, "key", track.key)
        camelot = _current_or_snapshot(current_metadata, "camelot", track.camelot)
        genre = _current_or_snapshot(current_metadata, "genre", track.genre)
        duration_sec = _current_or_snapshot(current_metadata, "duration_sec", track.duration_sec)
        restored_track = SetPoolTrack(
            set_id=set_obj.id,
            source_id=source_id_map[track.source_id],
            track_id=track.track_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            genre=genre,
            bpm=bpm,
            key=key,
            camelot=camelot,
            energy=track.energy,
            isrc=track.isrc,
            duration_sec=duration_sec,
            artwork_url=track.artwork_url,
            dedupe_sig=track.dedupe_sig,
            # Restore enqueues no background worker, so derive a terminal status
            # from the track's contract fields rather than trusting the snapshot's
            # stored value. A pre-change snapshot has no enrichment_status (it
            # defaults to "pending"), which would otherwise report in_progress
            # forever with nothing to clear it (mirrors the 064 backfill).
            enrichment_status=_merged_enrichment_status(
                current_metadata,
                bpm=bpm,
                key=key,
                genre=genre,
                duration_sec=duration_sec,
            ),
            created_at=track.created_at,
        )
        db.add(restored_track)
        db.flush()
        pool_track_id_map[track.id] = restored_track.id

    for slot in snapshot.slots:
        db.add(
            SetSlot(
                set_id=set_obj.id,
                position=slot.position,
                track_id=_remap_synthetic_pool_track_id(slot.track_id, pool_track_id_map),
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
