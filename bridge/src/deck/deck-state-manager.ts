/**
 * Deck State Manager
 *
 * Manages a per-deck state machine to determine when tracks are truly "live"
 * (playing to the audience) vs being cued/prepared.
 *
 * State transitions:
 *   EMPTY -> LOADED (track loaded)
 *   LOADED -> CUEING (play started)
 *   CUEING -> PLAYING (threshold reached + conditions met)
 *   CUEING -> LOADED (paused)
 *   PLAYING -> ENDED (long pause)
 *   Any -> EMPTY (track unloaded)
 *   Any -> LOADED (new track loaded)
 */
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";
import type {
  DeckState,
  DeckStateType,
  DeckStateManagerConfig,
  DeckLiveEvent,
} from "./deck-state.js";
import type { TrackInfo } from "../shared/track-types.js";
import { MILLISECONDS_PER_SECOND } from "../shared/time-units.js";

/** Maximum number of decks to prevent unbounded map growth */
const MAX_DECKS = 16;

export interface DeckStateManagerEventMap {
  deckLive: [event: DeckLiveEvent];
  nowPlayingCleared: [];
  log: [message: string];
}

/**
 * Creates a fresh deck state for a given deck ID.
 */
function createEmptyDeckState(deckId: string): DeckState {
  return {
    deckId,
    state: "EMPTY",
    track: null,
    isPlaying: false,
    playStartTime: null,
    accumulatedPlayTime: 0,
    lastPauseTime: null,
    faderLevel: 1.0, // Default to full for systems without fader data
    isMaster: false,
    hasBeenReported: false,
  };
}

export class DeckStateManager extends TypedEventEmitter<DeckStateManagerEventMap> {
  private readonly config: DeckStateManagerConfig;
  private readonly decks: Map<string, DeckState>;
  private readonly timers: Map<string, NodeJS.Timeout>;
  private destroyed = false;

  /** The deck currently reported as "now playing" - has priority over other decks */
  private currentNowPlayingDeckId: string | null = null;

  /** Timer for switching away from current now-playing deck after pause */
  private nowPlayingSwitchTimer: NodeJS.Timeout | null = null;

  constructor(config: DeckStateManagerConfig) {
    super();
    this.config = config;
    this.decks = new Map();
    this.timers = new Map();
  }

  /** Get IDs for decks currently tracked by this manager. */
  getDeckIds(): readonly string[] {
    return [...this.decks.keys()];
  }

  /**
   * Get a deck's state, creating it if absent and evicting an inactive deck at capacity.
   * @param deckId - The deck identifier (e.g., "1A", "2B")
   * @returns The current deck state
   * @throws Error if the maximum deck limit is reached and every deck is active
   */
  getOrCreateDeckState(deckId: string): DeckState {
    let state = this.decks.get(deckId);
    if (!state) {
      if (this.decks.size >= MAX_DECKS) {
        // Evict the oldest EMPTY/ENDED deck instead of throwing
        const evicted = this.evictStaleDeck();
        if (!evicted) {
          throw new Error(`Maximum deck limit (${MAX_DECKS}) reached — all decks are active`);
        }
      }
      state = createEmptyDeckState(deckId);
      this.decks.set(deckId, state);
    }
    return state;
  }

  /** Inspect an existing deck without creating or evicting any deck. */
  findDeckState(deckId: string): DeckState | undefined {
    return this.decks.get(deckId);
  }

  /**
   * Evict a stale deck to make room for a new one.
   * Prefers EMPTY, then ENDED, then LOADED, then CUEING as last resort.
   * Never evicts PLAYING decks. Returns true if a deck was evicted.
   */
  private evictStaleDeck(): boolean {
    for (const priority of ["EMPTY", "ENDED", "LOADED", "CUEING"] as const) {
      for (const [id, state] of this.decks) {
        if (state.state === priority) {
          this.emitLog(`Deck ${id}: Evicted (${priority}) to make room for new deck`);
          this.clearTimer(id);
          if (id === this.currentNowPlayingDeckId) {
            this.currentNowPlayingDeckId = null;
          }
          this.decks.delete(id);
          return true;
        }
      }
    }
    return false;
  }

  /**
   * Update track information for a deck.
   */
  updateTrackInfo(deckId: string, track: TrackInfo | null): void {
    const currentState = this.getOrCreateDeckState(deckId);

    // Clear any pending timers
    this.clearTimer(deckId);

    const wasNowPlaying = deckId === this.currentNowPlayingDeckId;

    if (track === null) {
      // Track unloaded - reset to empty
      this.emitLog(`Deck ${deckId}: Track unloaded (was: ${currentState.track?.title ?? 'empty'}) → EMPTY`);
      this.decks.set(deckId, {
        ...createEmptyDeckState(deckId),
        faderLevel: currentState.faderLevel,
        isMaster: currentState.isMaster,
      });

      // If this was the now-playing deck, scan for a new candidate
      if (wasNowPlaying) {
        this.emitLog(`Deck ${deckId}: Was now-playing, scanning for new candidate after unload`);
        this.clearNowPlayingSwitchTimer();
        this.scanForNowPlayingCandidate();
      }
      return;
    }

    // New track loaded - reset state but keep fader/master
    this.emitLog(`Deck ${deckId}: Track loaded "${track.title}" by ${track.artist} → LOADED`);
    this.decks.set(deckId, {
      ...createEmptyDeckState(deckId),
      state: "LOADED",
      track: { ...track },
      faderLevel: currentState.faderLevel,
      isMaster: currentState.isMaster,
    });

    // If this was the now-playing deck and it got a new track, scan for a new candidate
    if (wasNowPlaying) {
      this.emitLog(`Deck ${deckId}: Was now-playing, scanning for new candidate after track change`);
      this.clearNowPlayingSwitchTimer();
      this.scanForNowPlayingCandidate();
    }
  }

  /**
   * Update play/pause state for a deck.
   */
  updatePlayState(deckId: string, isPlaying: boolean): void {
    const currentState = this.getOrCreateDeckState(deckId);

    // Can't play if no track loaded
    if (currentState.state === "EMPTY") {
      return;
    }

    // Already in this state
    if (currentState.isPlaying === isPlaying) {
      return;
    }

    if (isPlaying) {
      this.handlePlayStart(deckId, currentState);
    } else {
      this.handlePlayStop(deckId, currentState);
    }
  }

  /**
   * Handle play starting on a deck.
   */
  private handlePlayStart(deckId: string, currentState: DeckState): void {
    const now = Date.now();
    let accumulatedTime = 0;

    // Check if we're resuming within grace period
    if (currentState.lastPauseTime !== null) {
      const pauseDuration = now - currentState.lastPauseTime;
      const graceMs = this.config.pauseGraceSeconds * MILLISECONDS_PER_SECOND;

      if (pauseDuration <= graceMs) {
        // Within grace period - keep accumulated time
        accumulatedTime = currentState.accumulatedPlayTime;
        this.emitLog(`Deck ${deckId}: Resumed within grace period (${pauseDuration}ms pause, accumulated ${(accumulatedTime / MILLISECONDS_PER_SECOND).toFixed(1)}s)`);
      } else {
        this.emitLog(`Deck ${deckId}: Pause exceeded grace period (${pauseDuration}ms > ${graceMs}ms), resetting accumulated time`);
      }
    }

    // Determine new state
    let newState: DeckStateType = "CUEING";
    if (currentState.state === "PLAYING" || currentState.state === "ENDED") {
      // Resuming from PLAYING or ENDED state
      newState = "PLAYING";
    }

    this.emitLog(`Deck ${deckId}: Play started → ${newState} (from ${currentState.state})`);

    this.decks.set(deckId, {
      ...currentState,
      state: newState,
      isPlaying: true,
      playStartTime: now,
      accumulatedPlayTime: accumulatedTime,
      lastPauseTime: null,
    });

    // If this is the current now-playing deck resuming, cancel the switch timer
    if (deckId === this.currentNowPlayingDeckId) {
      this.clearNowPlayingSwitchTimer();
      this.emitLog(`Deck ${deckId}: Cancelled now-playing switch timer (deck resumed)`);
    }

    // If CUEING, start the threshold timer
    if (newState === "CUEING") {
      const thresholdMs = this.config.liveThresholdSeconds * MILLISECONDS_PER_SECOND;
      const remainingMs = Math.max(0, thresholdMs - accumulatedTime);
      this.emitLog(`Deck ${deckId}: Starting threshold timer (${(remainingMs / MILLISECONDS_PER_SECOND).toFixed(1)}s remaining of ${this.config.liveThresholdSeconds}s)`);
      this.startThresholdTimer(deckId, accumulatedTime);
    }
  }

  /**
   * Handle play stopping on a deck.
   */
  private handlePlayStop(deckId: string, currentState: DeckState): void {
    const now = Date.now();

    // Calculate how much play time we accumulated
    let totalAccumulated = currentState.accumulatedPlayTime;
    if (currentState.playStartTime !== null) {
      totalAccumulated += now - currentState.playStartTime;
    }

    // Clear threshold timer
    this.clearTimer(deckId);

    // Determine new state based on current state
    let newState: DeckStateType;
    if (currentState.state === "PLAYING") {
      // Stay in PLAYING during brief pause
      newState = "PLAYING";
      this.emitLog(`Deck ${deckId}: Paused in PLAYING state (accumulated ${(totalAccumulated / MILLISECONDS_PER_SECOND).toFixed(1)}s), starting ${this.config.pauseGraceSeconds}s grace timer`);
      // Start grace period timer
      this.startGracePeriodTimer(deckId);

      // If this is the current now-playing deck, start the switch timer
      // This allows switching to another deck if this one stays paused
      if (deckId === this.currentNowPlayingDeckId) {
        this.emitLog(`Deck ${deckId}: Starting ${this.config.nowPlayingPauseSeconds}s now-playing switch timer`);
        this.startNowPlayingSwitchTimer();
      }
    } else {
      // CUEING -> LOADED
      newState = "LOADED";
      this.emitLog(`Deck ${deckId}: Paused during cueing → LOADED (accumulated ${(totalAccumulated / MILLISECONDS_PER_SECOND).toFixed(1)}s)`);
    }

    this.decks.set(deckId, {
      ...currentState,
      state: newState,
      isPlaying: false,
      playStartTime: null,
      accumulatedPlayTime: totalAccumulated,
      lastPauseTime: now,
    });
  }

  /**
   * Start the threshold timer for transitioning CUEING -> PLAYING.
   */
  private startThresholdTimer(deckId: string, accumulatedTime: number): void {
    if (this.destroyed) return;
    const thresholdMs = this.config.liveThresholdSeconds * MILLISECONDS_PER_SECOND;
    const remainingMs = Math.max(0, thresholdMs - accumulatedTime);

    const timer = setTimeout(() => {
      this.onThresholdReached(deckId);
    }, remainingMs);

    this.timers.set(deckId, timer);
  }

  /**
   * Start the grace period timer for transitioning PLAYING -> ENDED.
   */
  private startGracePeriodTimer(deckId: string): void {
    if (this.destroyed) return;
    const graceMs = this.config.pauseGraceSeconds * MILLISECONDS_PER_SECOND;

    const timer = setTimeout(() => {
      this.onGracePeriodExpired(deckId);
    }, graceMs);

    this.timers.set(deckId, timer);
  }

  /**
   * Called when the play threshold is reached.
   */
  private onThresholdReached(deckId: string): void {
    const currentState = this.getOrCreateDeckState(deckId);

    // Must still be in CUEING state and playing
    if (currentState.state !== "CUEING" || !currentState.isPlaying) {
      this.emitLog(`Deck ${deckId}: Threshold timer fired but state=${currentState.state} isPlaying=${currentState.isPlaying}, ignoring`);
      return;
    }

    this.emitLog(`Deck ${deckId}: Threshold reached → PLAYING (track: "${currentState.track?.title}")`);
    this.decks.set(deckId, {
      ...currentState,
      state: "PLAYING",
    });

    this.checkAndReport(deckId);
  }

  /**
   * Called when grace period expires after pausing in PLAYING state.
   */
  private onGracePeriodExpired(deckId: string): void {
    const currentState = this.getOrCreateDeckState(deckId);

    // Must be in PLAYING state and not currently playing
    if (currentState.state !== "PLAYING" || currentState.isPlaying) {
      return;
    }

    this.emitLog(`Deck ${deckId}: Grace period expired → ENDED (track: "${currentState.track?.title}")`);
    this.decks.set(deckId, {
      ...currentState,
      state: "ENDED",
    });

    // If this was the now-playing deck, scan for a new candidate immediately
    if (deckId === this.currentNowPlayingDeckId) {
      this.emitLog(`Deck ${deckId}: Was now-playing, scanning for new candidate after grace period`);
      this.clearNowPlayingSwitchTimer();
      this.scanForNowPlayingCandidate();
    }
  }

  /**
   * Update the fader level for a deck.
   */
  updateFaderLevel(deckId: string, level: number): void {
    const currentState = this.getOrCreateDeckState(deckId);

    // Clamp level to 0-1 range
    const clampedLevel = Math.max(0, Math.min(1, level));

    const wasLow = currentState.faderLevel === 0;
    const isNowUp = clampedLevel > 0;

    this.decks.set(deckId, {
      ...currentState,
      faderLevel: clampedLevel,
    });

    // If fader just came up and we're in PLAYING, check if we should report
    if (wasLow && isNowUp && currentState.state === "PLAYING") {
      this.emitLog(`Deck ${deckId}: Fader raised (${clampedLevel.toFixed(2)}), checking report conditions`);
      this.checkAndReport(deckId);
    }

    // If the current now-playing deck's fader drops to 0, start the switch timer
    // This handles the common DJ fade-out transition pattern
    if (deckId === this.currentNowPlayingDeckId && clampedLevel === 0 && !wasLow) {
      this.emitLog(`Deck ${deckId}: Now-playing deck fader dropped to 0, starting switch timer`);
      this.startNowPlayingSwitchTimer();
    }
  }

  /**
   * Set which deck is the master deck.
   */
  setMasterDeck(deckId: string): void {
    const previousMasterState = [...this.decks.values()].find((d) => d.isMaster);

    if (!previousMasterState || previousMasterState.deckId !== deckId) {
      this.emitLog(`Deck ${deckId}: Set as master deck (was: ${previousMasterState?.deckId ?? 'none'})`);
    }

    // Clear master from all decks
    for (const [id, state] of this.decks) {
      if (state.isMaster) {
        this.decks.set(id, {
          ...state,
          isMaster: false,
        });
      }
    }

    const currentState = this.getOrCreateDeckState(deckId);
    const updatedState: DeckState = {
      ...currentState,
      isMaster: true,
    };
    this.decks.set(deckId, updatedState);

    // If this deck is in PLAYING and wasn't master before, check if we should report
    if (
      updatedState.state === "PLAYING" &&
      (!previousMasterState || previousMasterState.deckId !== deckId)
    ) {
      this.checkAndReport(deckId);
    }
  }

  /**
   * Check if any deck has been explicitly set as master.
   */
  private hasMasterDeck(): boolean {
    return [...this.decks.values()].some((d) => d.isMaster);
  }

  /**
   * Check if a track should be reported and emit event if so.
   * Implements "now playing priority" - current now-playing deck has priority.
   */
  private checkAndReport(deckId: string): void {
    const state = this.findDeckState(deckId);
    if (!state) return;
    const blockReason = this.reportBlockReason(state);
    if (blockReason) {
      this.emitLog(`Deck ${deckId}: Report check — blocked (${blockReason})`);
      return;
    }

    // Now Playing Priority: if another deck is currently "now playing" and still active,
    // don't switch to this deck yet
    if (this.currentNowPlayingDeckId !== null && this.currentNowPlayingDeckId !== deckId) {
      const currentNowPlaying = this.findDeckState(this.currentNowPlayingDeckId);
      // If current now-playing deck is still playing or only briefly paused, don't switch
      if (currentNowPlaying?.isPlaying || currentNowPlaying?.state === "PLAYING") {
        this.emitLog(`Deck ${deckId}: Report check — blocked (deck ${this.currentNowPlayingDeckId} has now-playing priority)`);
        return;
      }
    }

    // All conditions met - report!
    if (state.track) {
      this.emitLog(`Deck ${deckId}: REPORTING "${state.track.title}" by ${state.track.artist} (fader=${state.faderLevel.toFixed(2)}, master=${state.isMaster})`);

      this.decks.set(deckId, {
        ...state,
        hasBeenReported: true,
      });

      // Cancel any pending switch timer since we're now switching to this deck
      this.clearNowPlayingSwitchTimer();

      // This deck is now the "now playing" deck
      this.currentNowPlayingDeckId = deckId;

      const event: DeckLiveEvent = {
        deckId,
        track: { ...state.track },
      };

      this.emit("deckLive", event);
    }
  }

  /**
   * Start the now-playing switch timer when the current now-playing deck pauses.
   * If timer expires and another deck is playing, switch to that deck.
   */
  private startNowPlayingSwitchTimer(): void {
    if (this.destroyed) return;
    this.clearNowPlayingSwitchTimer();

    const pauseMs = this.config.nowPlayingPauseSeconds * MILLISECONDS_PER_SECOND;

    this.nowPlayingSwitchTimer = setTimeout(() => {
      this.onNowPlayingSwitchTimerExpired();
    }, pauseMs);
  }

  /**
   * Clear the now-playing switch timer.
   */
  private clearNowPlayingSwitchTimer(): void {
    if (this.nowPlayingSwitchTimer) {
      clearTimeout(this.nowPlayingSwitchTimer);
      this.nowPlayingSwitchTimer = null;
    }
  }

  /**
   * Called when the now-playing switch timer expires.
   */
  private onNowPlayingSwitchTimerExpired(): void {
    this.nowPlayingSwitchTimer = null;
    this.emitLog(`Now-playing switch timer expired (was deck ${this.currentNowPlayingDeckId}), scanning for candidate`);
    this.scanForNowPlayingCandidate();
  }

  /**
   * Scan all decks for a candidate to become the new "now playing" deck.
   * Clears currentNowPlayingDeckId first, then finds the best candidate
   * (sorted by deck ID for deterministic order).
   */
  private scanForNowPlayingCandidate(): void {
    const previousDeckId = this.currentNowPlayingDeckId;
    this.currentNowPlayingDeckId = null;

    // Sort deck IDs numerically for deterministic behavior
    const sortedDeckIds = [...this.decks.keys()].sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true })
    );

    // Find another deck that is in PLAYING state and currently playing
    for (const deckId of sortedDeckIds) {
      if (deckId === previousDeckId) {
        continue;
      }

      const state = this.decks.get(deckId)!;

      if (this.reportBlockReason(state) === null) {
        // Found a candidate - report it
        this.emitLog(`Deck ${deckId}: Switching now-playing to this deck ("${state.track?.title}")`);
        this.decks.set(deckId, {
          ...state,
          hasBeenReported: true,
        });

        this.currentNowPlayingDeckId = deckId;
        this.clearNowPlayingSwitchTimer();

        if (state.track) {
          const event: DeckLiveEvent = {
            deckId,
            track: { ...state.track },
          };
          this.emit("deckLive", event);
        }
        return;
      }
    }

    // No other deck found - clear current now playing
    this.emitLog('No switch candidate found, clearing now-playing deck');
    this.emit("nowPlayingCleared");
  }

  /**
   * Check if a track should be reported (external check).
   */
  shouldReportTrack(deckId: string): boolean {
    const state = this.findDeckState(deckId);
    return state !== undefined && this.reportBlockReason(state) === null;
  }

  private reportBlockReason(state: DeckState): string | null {
    if (state.state !== "PLAYING" || state.hasBeenReported) {
      return state.hasBeenReported ? "already reported" : `state=${state.state}, need PLAYING`;
    }
    if (this.config.useFaderDetection && state.faderLevel === 0) {
      return "fader is down";
    }
    if (this.config.masterDeckPriority && this.hasMasterDeck() && !state.isMaster) {
      return "not master deck";
    }
    return null;
  }

  /**
   * Clear a pending timer for a deck.
   */
  private clearTimer(deckId: string): void {
    const timer = this.timers.get(deckId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(deckId);
    }
  }

  /**
   * Get the current now-playing deck ID.
   * Exposed for testing purposes.
   */
  getCurrentNowPlayingDeckId(): string | null {
    return this.currentNowPlayingDeckId;
  }

  /**
   * Emit a diagnostic log message.
   * Consumers can listen for 'log' events to capture these messages.
   */
  private emitLog(message: string): void {
    this.emit("log", message);
  }

  /**
   * Reset all deck state without removing event listeners.
   * Use on plugin reconnect to clear stale state from the old connection.
   */
  reset(): void {
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.clearNowPlayingSwitchTimer();
    this.decks.clear();
    this.currentNowPlayingDeckId = null;
    this.emitLog("All deck state reset (plugin reconnecting)");
  }

  /** Release timers and listeners when the manager is no longer needed. */
  destroy(): void {
    this.destroyed = true;
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.clearNowPlayingSwitchTimer();
    this.removeAllListeners();
  }
}
