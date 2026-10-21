/**
 * TypeScript interfaces for deck state management.
 */
import type { TrackInfo } from "../shared/track-types.js";

/** Possible states for a deck in the state machine */
export type DeckStateType = "EMPTY" | "LOADED" | "CUEING" | "PLAYING" | "ENDED";

/** Complete state of a single deck */
export interface DeckState {
  deckId: string;
  state: DeckStateType;
  track: TrackInfo | null;
  isPlaying: boolean;
  playStartTime: number | null;
  accumulatedPlayTime: number;
  lastPauseTime: number | null;
  faderLevel: number;
  isMaster: boolean;
  hasBeenReported: boolean;
}

/** Immutable copy of deck state exposed to status consumers. */
export type DeckStateSnapshot = Readonly<Omit<DeckState, "track">> & {
  readonly track: Readonly<TrackInfo> | null;
};

/** Read-only deck status returned by PluginBridge. */
export interface DeckStatusSnapshot {
  readonly deckCount: number;
  readonly deckStates: readonly DeckStateSnapshot[];
}

/** Configuration options for the deck state manager */
export interface DeckStateManagerConfig {
  /** Seconds of continuous play before reporting track as live */
  liveThresholdSeconds: number;
  /** Seconds of pause before resetting accumulated play time */
  pauseGraceSeconds: number;
  /** Seconds current "now playing" deck must pause before switching to another */
  nowPlayingPauseSeconds: number;
  /** Whether to require fader > 0 for live detection */
  useFaderDetection: boolean;
  /** Whether to only report from master deck */
  masterDeckPriority: boolean;
}

/** Event payload when a deck goes live */
export interface DeckLiveEvent {
  deckId: string;
  track: TrackInfo;
}
