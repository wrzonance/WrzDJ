'use client';

/**
 * Three-tier vibe display (issue #391) — DJ's own override, community
 * consensus, and globally-cached LLM guess, side by side. Low-confidence
 * LLM guesses are flagged for review. Optional callbacks expose the v1.1
 * write controls without coupling this renderer to API calls.
 */

import { useEffect, useState } from 'react';
import type { TrackVibeState } from '@/lib/api-types';
import styles from '../setbuilder.module.css';

type TierSource = 'own' | 'community' | 'llm';
type OverridePayload = { energy: number | null; mood: string | null };

interface TierView {
  source: TierSource;
  label: string;
  ariaName: string;
  energy: number | null;
  mood: string | null;
  suffix: string | null;
  title: string | undefined;
  warn: boolean;
}

interface SourceIndicator {
  label: string;
  aria: string;
}

interface VibeTiersProps {
  state: TrackVibeState;
  busy?: boolean;
  onAgree?: () => void;
  onSaveOverride?: (payload: OverridePayload) => void;
}

function buildTiers(state: TrackVibeState): TierView[] {
  return [
    {
      source: 'own',
      label: 'You',
      ariaName: 'Your vibe',
      energy: state.own?.energy ?? null,
      mood: state.own?.mood ?? null,
      suffix: null,
      title: undefined,
      warn: false,
    },
    {
      source: 'community',
      label: 'Crowd',
      ariaName: 'Community vibe',
      energy: state.community?.energy ?? null,
      mood: state.community?.mood ?? null,
      suffix: state.community ? `·${state.community.sample_size}` : null,
      title: state.community
        ? `Community consensus from ${state.community.sample_size} DJs`
        : undefined,
      warn: false,
    },
    {
      source: 'llm',
      label: 'AI',
      ariaName: 'AI vibe',
      energy: state.llm?.energy ?? null,
      mood: state.llm?.mood ?? null,
      suffix: null,
      title: state.llm
        ? state.llm.low_confidence
          ? 'Low confidence — review'
          : `AI guess (${state.llm.llm_provider} · ${state.llm.llm_model})`
        : undefined,
      warn: state.llm?.low_confidence ?? false,
    },
  ];
}

function indicatorFor(state: TrackVibeState): SourceIndicator {
  if (state.own) return { label: 'You', aria: 'Vibe source: your override' };
  if (state.community) return { label: 'Crowd', aria: 'Vibe source: community consensus' };
  if (state.llm) return { label: 'AI', aria: 'Vibe source: AI guess' };
  return { label: 'None', aria: 'Vibe source: not set' };
}

function hasNonOwnVibe(state: TrackVibeState): boolean {
  return Boolean(
    state.community?.energy != null ||
      state.community?.mood != null ||
      state.llm?.energy != null ||
      state.llm?.mood != null,
  );
}

function chipAria(tier: TierView): string {
  const parts: string[] = [];
  if (tier.energy != null) parts.push(`energy ${tier.energy}`);
  if (tier.mood != null) parts.push(`mood ${tier.mood}`);
  return `${tier.ariaName}: ${parts.length ? parts.join(', ') : 'not set'}`;
}

export default function VibeTiers({
  state,
  busy = false,
  onAgree,
  onSaveOverride,
}: VibeTiersProps) {
  const [editing, setEditing] = useState(false);
  const [energy, setEnergy] = useState('');
  const [mood, setMood] = useState('');
  const indicator = indicatorFor(state);

  useEffect(() => {
    if (editing) return;
    setEnergy(String(state.own?.energy ?? state.resolved.energy ?? ''));
    setMood(state.own?.mood ?? state.resolved.mood ?? '');
  }, [editing, state]);

  const saveOverride = () => {
    const trimmedEnergy = energy.trim();
    const parsedEnergy = trimmedEnergy === '' ? null : Math.round(Number(trimmedEnergy));
    onSaveOverride?.({
      energy: Number.isFinite(parsedEnergy) ? parsedEnergy : null,
      mood: mood.trim() || null,
    });
    setEditing(false);
  };

  return (
    <div className={styles.vibeBlock}>
      <div className={styles.vibeTopRow}>
        <span className={styles.vibeSource} aria-label={indicator.aria}>
          {indicator.label}
        </span>
        <div className={styles.vibeTiers}>
          {buildTiers(state).map((tier) => {
            const empty = tier.energy == null && tier.mood == null;
            // Per-field winner: a tier wins if it supplies the resolved energy OR mood.
            const winner =
              state.resolved.energy_source === tier.source ||
              state.resolved.mood_source === tier.source;
            const classes = [
              styles.vibeChip,
              empty ? styles.vibeEmpty : '',
              tier.warn ? styles.vibeLow : '',
              !empty && winner ? styles.vibeWinner : '',
            ]
              .filter(Boolean)
              .join(' ');
            return (
              <span
                key={tier.source}
                className={classes}
                title={tier.title}
                aria-label={chipAria(tier)}
              >
                {tier.warn && <span aria-hidden>⚠</span>}
                <span className={styles.vibeChipLabel}>{tier.label}</span>
                {empty ? (
                  <span>—</span>
                ) : (
                  <>
                    {tier.energy != null && <span>E{tier.energy}</span>}
                    {tier.mood != null && <span>{tier.mood}</span>}
                    {tier.suffix && <span>{tier.suffix}</span>}
                  </>
                )}
              </span>
            );
          })}
        </div>
        {(onAgree || onSaveOverride) && (
          <span className={styles.vibeActions}>
            {onAgree && (
              <button
                type="button"
                className={styles.vibeActionBtn}
                onClick={onAgree}
                disabled={busy || !hasNonOwnVibe(state)}
              >
                Agree
              </button>
            )}
            {onSaveOverride && (
              <button
                type="button"
                className={styles.vibeActionBtn}
                onClick={() => setEditing((open) => !open)}
                disabled={busy}
              >
                Tweak
              </button>
            )}
          </span>
        )}
      </div>
      {editing && onSaveOverride && (
        <div className={styles.vibeEditForm}>
          <label className={styles.vibeEditLabel}>
            <span>Energy</span>
            <input
              className={styles.vibeNumber}
              type="number"
              min="0"
              max="10"
              value={energy}
              onChange={(e) => setEnergy(e.target.value)}
            />
          </label>
          <label className={styles.vibeEditLabel}>
            <span>Mood</span>
            <input
              className={styles.vibeMood}
              maxLength={50}
              value={mood}
              onChange={(e) => setMood(e.target.value)}
            />
          </label>
          <button type="button" className={styles.vibeActionBtn} onClick={saveOverride}>
            Save
          </button>
          <button type="button" className={styles.vibeActionBtn} onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
