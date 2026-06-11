/**
 * VibeTiers component tests (issue #391) — read-only three-tier vibe chips:
 * per-tier values, empty placeholders, low-confidence AI flag, sample size,
 * and winner highlight from the resolved precedence.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { TrackVibeState } from '@/lib/api-types';
import styles from '../../setbuilder.module.css';
import VibeTiers from '../VibeTiers';

type LlmTier = NonNullable<TrackVibeState['llm']>;

function makeLlm(overrides: Partial<LlmTier> = {}): LlmTier {
  return {
    energy: 5,
    mood: 'happy',
    confidence: 0.92,
    low_confidence: false,
    llm_provider: 'anthropic_apikey',
    llm_model: 'claude-haiku-4-5',
    dance_floor: null,
    era: null,
    sing_along: null,
    transitional_role: null,
    ...overrides,
  };
}

function makeState(overrides: Partial<TrackVibeState> = {}): TrackVibeState {
  return {
    pool_track_id: 11,
    vibe_key: 'event artist|event song',
    own: { energy: 9, mood: null },
    community: { energy: 7, mood: 'dark', sample_size: 3 },
    llm: makeLlm(),
    resolved: { energy: 9, energy_source: 'own', mood: 'dark', mood_source: 'community' },
    ...overrides,
  };
}

describe('VibeTiers', () => {
  it('renders all three tiers side-by-side with their values', () => {
    render(<VibeTiers state={makeState()} />);
    // labels
    expect(screen.getByText('You')).toBeTruthy();
    expect(screen.getByText('Crowd')).toBeTruthy();
    expect(screen.getByText('AI')).toBeTruthy();
    // own: E9 (no mood)
    expect(screen.getByText('E9')).toBeTruthy();
    // community: E7 "dark" with sample size
    expect(screen.getByText('E7')).toBeTruthy();
    expect(screen.getByText('dark')).toBeTruthy();
    expect(screen.getByText('·3')).toBeTruthy();
    // llm: E5 "happy"
    expect(screen.getByText('E5')).toBeTruthy();
    expect(screen.getByText('happy')).toBeTruthy();
  });

  it('renders dimmed placeholders for missing tiers', () => {
    render(
      <VibeTiers
        state={makeState({
          own: null,
          community: null,
          llm: null,
          resolved: { energy: null, energy_source: null, mood: null, mood_source: null },
        })}
      />
    );
    expect(screen.getAllByText('—')).toHaveLength(3);
    const own = screen.getByLabelText('Your vibe: not set');
    const crowd = screen.getByLabelText('Community vibe: not set');
    const ai = screen.getByLabelText('AI vibe: not set');
    for (const chip of [own, crowd, ai]) {
      expect(chip.className).toContain(styles.vibeEmpty);
    }
  });

  it('flags low-confidence AI guesses for review', () => {
    const { unmount } = render(
      <VibeTiers state={makeState({ llm: makeLlm({ low_confidence: true, confidence: 0.3 }) })} />
    );
    expect(screen.getByText('⚠')).toBeTruthy();
    const lowChip = screen.getByLabelText('AI vibe: energy 5, mood happy');
    expect(lowChip.getAttribute('title')).toBe('Low confidence — review');
    expect(lowChip.className).toContain(styles.vibeLow);
    unmount();

    render(<VibeTiers state={makeState()} />);
    expect(screen.queryByText('⚠')).toBeNull();
    const okChip = screen.getByLabelText('AI vibe: energy 5, mood happy');
    expect(okChip.getAttribute('title')).toBe('AI guess (anthropic_apikey · claude-haiku-4-5)');
    expect(okChip.className).not.toContain(styles.vibeLow);
  });

  it('exposes community sample size and highlights every per-field winner', () => {
    render(<VibeTiers state={makeState()} />);
    const crowd = screen.getByLabelText('Community vibe: energy 7, mood dark');
    expect(crowd.getAttribute('title')).toBe('Community consensus from 3 DJs');
    // energy_source === 'own' → the You chip wins energy;
    // mood_source === 'community' → the Crowd chip wins mood — BOTH highlight.
    const own = screen.getByLabelText('Your vibe: energy 9');
    expect(own.className).toContain(styles.vibeWinner);
    expect(crowd.className).toContain(styles.vibeWinner);
    const ai = screen.getByLabelText('AI vibe: energy 5, mood happy');
    expect(ai.className).not.toContain(styles.vibeWinner);
  });
});
