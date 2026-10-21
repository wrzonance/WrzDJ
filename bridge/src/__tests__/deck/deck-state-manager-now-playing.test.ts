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

  describe("Now Playing Priority System", () => {
    const track1: TrackInfo = {
      title: "Song One",
      artist: "Artist One",
    };
    const track2: TrackInfo = {
      title: "Song Two",
      artist: "Artist Two",
    };

    it("sets currentNowPlayingDeckId when first deck goes live", () => {
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);

      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");
    });

    it("does not switch to new deck while current now-playing deck is still playing", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");

      // Deck 2 starts playing and meets threshold
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Should NOT have switched - deck 1 is still playing
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");
    });

    it("switches to new deck after current now-playing deck's grace period expires", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 starts playing and meets threshold
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Deck 1 pauses
      manager.updatePlayState("1", false);

      // Before grace period, should NOT have switched
      vi.advanceTimersByTime(2999);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");

      // After grace period (3s), deck 1 → ENDED, scan finds deck 2
      vi.advanceTimersByTime(1);
      expect(deckLiveHandler).toHaveBeenCalledTimes(2);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
      expect(deckLiveHandler).toHaveBeenLastCalledWith({
        deckId: "2",
        track: track2,
      });
    });

    it("does NOT switch if current now-playing deck resumes within grace period", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);

      // Deck 2 starts playing
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Deck 1 pauses
      manager.updatePlayState("1", false);
      vi.advanceTimersByTime(2000); // 2 seconds pause (within 3s grace)

      // Deck 1 resumes before grace period expires
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(10000); // Wait to confirm no switch

      // Should NOT have switched - deck 1 resumed within grace period
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");
    });

    it("paused track on Deck 2 should NOT become now playing over active Deck 1", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 is playing and live
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 loads track, plays for 20s, then pauses
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(20000);
      manager.updatePlayState("2", false); // Paused

      // Deck 2 should NOT have been reported - Deck 1 was still playing
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");
    });

    it("clears currentNowPlayingDeckId when no other deck is playing after grace period", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Only deck 1 is playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");

      // Deck 1 pauses
      manager.updatePlayState("1", false);

      // After grace period (3s), deck 1 → ENDED, scan finds no candidate
      vi.advanceTimersByTime(3000);

      // currentNowPlayingDeckId should be cleared
      expect(manager.getCurrentNowPlayingDeckId()).toBeNull();
    });

    it("both decks pause simultaneously — paused PLAYING deck becomes candidate", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now-playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");

      // Deck 2 reaches PLAYING (blocked by priority — not reported)
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Both decks pause near the same time (deck 2 pauses 500ms later)
      manager.updatePlayState("1", false);
      vi.advanceTimersByTime(500);
      manager.updatePlayState("2", false);

      // Deck 1 grace period expires (3s from its pause = 2500ms more)
      // Deck 2 is paused but still in PLAYING state (within its own grace period)
      vi.advanceTimersByTime(2500);

      // Deck 2 (paused but PLAYING) should become the new candidate
      expect(deckLiveHandler).toHaveBeenCalledTimes(2);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
      expect(deckLiveHandler).toHaveBeenLastCalledWith({
        deckId: "2",
        track: track2,
      });
    });

    it("respects fader and master deck priority when switching", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing (master, fader up)
      manager.setMasterDeck("1");
      manager.updateFaderLevel("1", 1.0);
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 is playing but fader is down
      manager.updateTrackInfo("2", track2);
      manager.updateFaderLevel("2", 0); // Fader down
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Deck 1 pauses — grace period expires at 3s, then switch timer at 10s
      manager.updatePlayState("1", false);
      vi.advanceTimersByTime(10000);

      // Should NOT switch to deck 2 because fader is down
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
    });
  });

  describe("Re-check Mechanisms", () => {
    const track1: TrackInfo = {
      title: "Song One",
      artist: "Artist One",
    };
    const track2: TrackInfo = {
      title: "Song Two",
      artist: "Artist Two",
    };
    const track3: TrackInfo = {
      title: "Song Three",
      artist: "Artist Three",
    };

    it("track load on now-playing deck triggers scan → other PLAYING deck takes over", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");

      // Deck 2 is playing (reached PLAYING but blocked by priority)
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // DJ loads a new track on deck 1 (preparing next track)
      manager.updateTrackInfo("1", track3);

      // Scan should find deck 2 and switch
      expect(deckLiveHandler).toHaveBeenCalledTimes(2);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
      expect(deckLiveHandler).toHaveBeenLastCalledWith({
        deckId: "2",
        track: track2,
      });
    });

    it("track unload on now-playing deck triggers scan", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 is playing
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Track unloaded from deck 1
      manager.updateTrackInfo("1", null);

      // Should switch to deck 2
      expect(deckLiveHandler).toHaveBeenCalledTimes(2);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
    });

    it("grace period on now-playing deck triggers scan", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 is playing
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Deck 1 pauses
      manager.updatePlayState("1", false);

      // Grace period expires (3s) — scan triggers
      vi.advanceTimersByTime(3000);

      expect(deckLiveHandler).toHaveBeenCalledTimes(2);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
    });

    it("fader drop to 0 on now-playing deck starts switch timer", () => {
      // Use a manager without faderDetection to isolate the switch-timer behavior
      manager = new DeckStateManager({
        liveThresholdSeconds: 15,
        pauseGraceSeconds: 3,
        nowPlayingPauseSeconds: 10,
        useFaderDetection: false,
        masterDeckPriority: false,
      });

      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing with fader up
      manager.updateFaderLevel("1", 1.0);
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 is playing
      manager.updateFaderLevel("2", 1.0);
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Drop deck 1's fader to 0
      manager.updateFaderLevel("1", 0);

      // Before switch timer expires, no switch
      vi.advanceTimersByTime(9999);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // After switch timer (10s), deck 2 takes over
      vi.advanceTimersByTime(1);
      expect(deckLiveHandler).toHaveBeenCalledTimes(2);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
    });

    it("fader drop on non-now-playing deck does NOT start switch timer", () => {
      manager = new DeckStateManager({
        liveThresholdSeconds: 15,
        pauseGraceSeconds: 3,
        nowPlayingPauseSeconds: 10,
        useFaderDetection: false,
        masterDeckPriority: false,
      });

      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateFaderLevel("1", 1.0);
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Deck 2 is playing with fader up
      manager.updateFaderLevel("2", 1.0);
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Drop deck 2's fader (not the now-playing deck)
      manager.updateFaderLevel("2", 0);

      // Wait beyond switch timer
      vi.advanceTimersByTime(15000);

      // Should NOT have switched — only deck 1's fader matters for switch
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");
    });

    it("emits nowPlayingCleared when last playing deck ends with no candidate", () => {
      const clearedHandler = vi.fn();
      manager.on("nowPlayingCleared", clearedHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");

      // Deck 1 stops — grace period expires, no other deck available
      manager.updatePlayState("1", false);
      vi.advanceTimersByTime(3000); // grace period

      expect(manager.getCurrentNowPlayingDeckId()).toBeNull();
      expect(clearedHandler).toHaveBeenCalledTimes(1);
    });

    it("does NOT emit nowPlayingCleared when another deck takes over", () => {
      const clearedHandler = vi.fn();
      manager.on("nowPlayingCleared", clearedHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);

      // Deck 2 starts and reaches threshold
      manager.updateTrackInfo("2", track2);
      manager.updatePlayState("2", true);
      vi.advanceTimersByTime(15000);

      // Deck 1 stops — grace period expires, deck 2 should take over
      manager.updatePlayState("1", false);
      vi.advanceTimersByTime(3000);

      expect(manager.getCurrentNowPlayingDeckId()).toBe("2");
      expect(clearedHandler).not.toHaveBeenCalled();
    });

    it("non-now-playing deck load/unload does NOT trigger scan", () => {
      const deckLiveHandler = vi.fn();
      manager.on("deckLive", deckLiveHandler);

      // Deck 1 becomes now playing
      manager.updateTrackInfo("1", track1);
      manager.updatePlayState("1", true);
      vi.advanceTimersByTime(15000);
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);

      // Load and unload tracks on deck 2 (not now-playing)
      manager.updateTrackInfo("2", track2);
      manager.updateTrackInfo("2", null);
      manager.updateTrackInfo("2", track3);

      // Deck 1 should still be now-playing, no extra events
      expect(deckLiveHandler).toHaveBeenCalledTimes(1);
      expect(manager.getCurrentNowPlayingDeckId()).toBe("1");
    });
  });
});
