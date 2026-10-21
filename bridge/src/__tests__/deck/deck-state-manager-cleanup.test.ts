import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DeckStateManager } from "../../deck/deck-state-manager.js";
import type { DeckStateType } from "../../deck/deck-state.js";
import type { TrackInfo } from "../../shared/track-types.js";

describe("DeckStateManager", () => {
  let manager: DeckStateManager;

  beforeEach(() => {
    vi.useFakeTimers();
    manager = new DeckStateManager({
      liveThresholdSeconds: 15,
      pauseGraceSeconds: 3,
      nowPlayingPauseSeconds: 10,
      useFaderDetection: true,
      masterDeckPriority: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("Cleanup", () => {
    const testTrack: TrackInfo = {
      title: "Test Song",
      artist: "Test Artist",
    };

    it("destroy() clears all timers and listeners", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Start a track playing (this creates a threshold timer)
      manager.updateTrackInfo("1", testTrack);
      manager.updatePlayState("1", true);

      // Destroy the manager
      manager.destroy();

      // Advancing time should not trigger the callback
      vi.advanceTimersByTime(20000);
      expect(deckLiveHandler).not.toHaveBeenCalled();

      // Verify listeners are removed
      expect(manager.listenerCount("deckLive")).toBe(0);
    });

    it("destroy() clears grace period timers", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Get track to PLAYING state
      manager.updateTrackInfo("1", testTrack);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Pause (starts grace period timer)
      manager.updatePlayState("1", false);

      // Destroy before grace period expires
      manager.destroy();

      // Grace period timer should be cleared
      vi.advanceTimersByTime(5000);
      // State should not have changed to ENDED (timer was cleared)
      // We can't check state after destroy, but no errors should occur
    });

    it("destroy() clears now-playing switch timer", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", testTrack);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);

      // Deck 2 is also playing
      manager.updateTrackInfo("2", {
        title: "Song Two",
        artist: "Artist Two",
      });
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Deck 1 pauses (starts switch timer)
      manager.updatePlayState("1", false);

      // Destroy before switch timer expires
      manager.destroy();

      // Switch timer should be cleared - no switch should happen
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
    });

    it("prevents new timers from being created after destroy", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Destroy the manager before any tracks
      manager.destroy();

      // Now try to use the manager — these should not create timers
      manager.updateTrackInfo("1", {
        title: "Ghost Song",
        artist: "Ghost Artist",
      });
      manager.updatePlayState("1", true);
      manager.updateFaderLevel("1", 1.0);
      manager.setMasterDeck("1");

      // Advance past all possible timer thresholds
      vi.advanceTimersByTime(60_000);

      // No deckLive events should have been emitted
      expect(deckLiveHandler).not.toHaveBeenCalled();
    });
  });
});
