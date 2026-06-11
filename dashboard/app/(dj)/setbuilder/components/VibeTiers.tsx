'use client';

/**
 * Three-tier vibe display (issue #391) — DJ's own override, community
 * consensus, and globally-cached LLM guess, side by side. Read-only in v1
 * (write UX is v1.1). Low-confidence LLM guesses are flagged for review.
 */

import type { TrackVibeState } from '@/lib/api-types';
import styles from '../setbuilder.module.css';

type TierSource = 'own' | 'community' | 'llm';

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

function chipAria(tier: TierView): string {
  const parts: string[] = [];
  if (tier.energy != null) parts.push(`energy ${tier.energy}`);
  if (tier.mood != null) parts.push(`mood ${tier.mood}`);
  return `${tier.ariaName}: ${parts.length ? parts.join(', ') : 'not set'}`;
}

export default function VibeTiers({ state }: { state: TrackVibeState }) {
  const winner: TierSource | null = state.resolved.energy_source ?? state.resolved.mood_source;

  return (
    <div className={styles.vibeTiers}>
      {buildTiers(state).map((tier) => {
        const empty = tier.energy == null && tier.mood == null;
        const classes = [
          styles.vibeChip,
          empty ? styles.vibeEmpty : '',
          tier.warn ? styles.vibeLow : '',
          !empty && winner === tier.source ? styles.vibeWinner : '',
        ]
          .filter(Boolean)
          .join(' ');
        return (
          <span key={tier.source} className={classes} title={tier.title} aria-label={chipAria(tier)}>
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
  );
}
