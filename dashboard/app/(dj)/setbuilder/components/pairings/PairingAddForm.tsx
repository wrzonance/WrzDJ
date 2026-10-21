'use client';

import { useMemo, useState } from 'react';
import type { Pairing, PoolTrack } from '@/lib/api/types';
import { CompatibilityChips, TrackArt } from './PairingVisuals';

import pairingStyles from '../../setbuilder-pairings.module.css';
import sharedStyles from '../../setbuilder-shared.module.css';

function TrackPicker({
  label,
  pool,
  selected,
  excludeTrackId,
  onSelect,
}: {
  label: string;
  pool: PoolTrack[];
  selected: PoolTrack | null;
  excludeTrackId: string | null;
  onSelect: (track: PoolTrack | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const results = pool
    .filter((track) => track.track_id && track.track_id !== excludeTrackId)
    .filter((track) => `${track.title} ${track.artist}`.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 30);

  return (
    <div className={pairingStyles.pairingPicker}>
      <span className={pairingStyles.pairingRole}>{label}</span>
      {selected ? (
        <div className={pairingStyles.pairingPickerSelected}>
          <TrackArt track={selected} />
          <span>
            <strong>{selected.title}</strong>
            <small>{selected.artist}</small>
          </span>
          <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
            Change
          </button>
        </div>
      ) : (
        <button type="button" className={pairingStyles.pairingPickerEmpty} onClick={() => setOpen(true)}>
          Pick a track
        </button>
      )}
      {open && (
        <div className={pairingStyles.pairingPickerPopover}>
          <input
            className={sharedStyles.imInput}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search pool..."
            autoFocus
          />
          <div className={pairingStyles.pairingPickerResults}>
            {results.map((track) => (
              <button
                key={track.id}
                type="button"
                className={pairingStyles.pairingPickerResult}
                onClick={() => {
                  onSelect(track);
                  setOpen(false);
                  setQ('');
                }}
              >
                <TrackArt track={track} />
                <span>
                  <strong>{track.title}</strong>
                  <small>{track.artist} · {track.bpm ?? '-'} BPM · {track.camelot ?? track.key ?? '-'}</small>
                </span>
              </button>
            ))}
            {results.length === 0 && <div className={pairingStyles.pairingPickerNone}>No tracks found.</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export function PairingAddForm({
  pool,
  pairings,
  onCancel,
  onSave,
}: {
  pool: PoolTrack[];
  pairings: Pairing[];
  onCancel: () => void;
  onSave: (payload: { from_track_id: string; into_track_id: string; cue_in_sec: number | null; note: string | null; tags: string[] }) => Promise<void>;
}) {
  const [from, setFrom] = useState<PoolTrack | null>(null);
  const [into, setInto] = useState<PoolTrack | null>(null);
  const [note, setNote] = useState('');
  const [cue, setCue] = useState('');
  const [tagText, setTagText] = useState('');

  const tags = useMemo(
    () => tagText.split(',').map((tag) => tag.trim().replace(/^#/, '')).filter(Boolean),
    [tagText],
  );
  const duplicate = Boolean(
    from?.track_id &&
      into?.track_id &&
      pairings.some((p) => p.from_track_id === from.track_id && p.into_track_id === into.track_id),
  );
  const canSave = Boolean(from?.track_id && into?.track_id && !duplicate);

  return (
    <div className={pairingStyles.pairingAdd}>
      <h3>New pairing</h3>
      <p>Capture a directional transition you know works. It will be weighted into pass-1 scoring.</p>
      <div className={pairingStyles.pairingAddFlow}>
        <TrackPicker
          label="FROM"
          pool={pool}
          selected={from}
          excludeTrackId={into?.track_id ?? null}
          onSelect={setFrom}
        />
        <span className={pairingStyles.pairingHeroArrow}>-&gt;</span>
        <TrackPicker
          label="INTO"
          pool={pool}
          selected={into}
          excludeTrackId={from?.track_id ?? null}
          onSelect={setInto}
        />
      </div>
      {duplicate && from && into && (
        <div className={pairingStyles.pairingWarn}>
          A pairing already exists for {from.title} -&gt; {into.title}.
        </div>
      )}
      {from && into && !duplicate && (
        <div className={pairingStyles.pairingPreview}>
          <CompatibilityChips from={from} into={into} />
          <span className={pairingStyles.pairingMetricChip}>E {from.energy ?? '-'} -&gt; {into.energy ?? '-'}</span>
        </div>
      )}
      <label className={pairingStyles.pairingField}>
        <span>Note</span>
        <textarea
          className={pairingStyles.pairingTextarea}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="Cue point, mixer move, vibe read..."
        />
      </label>
      <div className={pairingStyles.pairingAddGrid}>
        <label className={pairingStyles.pairingField}>
          <span>Cue in seconds</span>
          <input className={sharedStyles.imInput} value={cue} onChange={(e) => setCue(e.target.value)} inputMode="numeric" />
        </label>
        <label className={pairingStyles.pairingField}>
          <span>Tags</span>
          <input className={sharedStyles.imInput} value={tagText} onChange={(e) => setTagText(e.target.value)} placeholder="wedding, safe, peak" />
        </label>
      </div>
      <div className={pairingStyles.pairingFooter}>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!canSave}
          onClick={async () => {
            if (!from?.track_id || !into?.track_id) return;
            try {
              await onSave({
                from_track_id: from.track_id,
                into_track_id: into.track_id,
                cue_in_sec: cue.trim() ? Math.max(0, Number.parseInt(cue, 10) || 0) : null,
                note: note.trim() || null,
                tags,
              });
            } catch {
              // The parent owns user-visible mutation errors.
            }
          }}
        >
          Save pairing
        </button>
      </div>
    </div>
  );
}
