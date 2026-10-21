import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DeckStateManager } from "../../deck/deck-state-manager.js";

// Regression: 57cfcdc6867f created or evicted decks during a report eligibility query.
describe("deck state access", () => {
  let manager: DeckStateManager;

  beforeEach(() => {
    manager = new DeckStateManager({
      liveThresholdSeconds: 15,
      pauseGraceSeconds: 3,
      nowPlayingPauseSeconds: 10,
      useFaderDetection: false,
      masterDeckPriority: false,
    });
  });

  afterEach(() => manager.destroy());

  it("does not create an unknown deck when checking whether to report it", () => {
    expect(manager.shouldReportTrack("unknown")).toBe(false);
    expect(manager.getDeckIds()).toEqual([]);
  });

  it("does not evict an existing deck when checking an unknown deck at capacity", () => {
    const deckIds = Array.from({ length: 16 }, (_, index) => String(index + 1));
    for (const deckId of deckIds) manager.getOrCreateDeckState(deckId);

    expect(manager.shouldReportTrack("unknown")).toBe(false);
    expect(manager.getDeckIds()).toEqual(deckIds);
  });

  it("can inspect existing state without creating absent decks", () => {
    manager.updateTrackInfo("1", { title: "Track", artist: "Artist" });

    expect(manager.findDeckState("1")?.track?.title).toBe("Track");
    expect(manager.findDeckState("unknown")).toBeUndefined();
    expect(manager.getDeckIds()).toEqual(["1"]);
  });
});
