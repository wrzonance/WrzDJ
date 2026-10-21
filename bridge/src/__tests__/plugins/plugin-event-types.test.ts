import { describe, expect, it } from "vitest";
import { SeratoPlugin } from "../../plugins/serato-plugin.js";

describe("equipment plugin event contract", () => {
  it("provides normalized payloads to typed listeners", () => {
    const plugin = new SeratoPlugin();
    const tracks: string[] = [];
    plugin.on("track", (event) => tracks.push(event.track?.title ?? "unloaded"));
    plugin.emit("track", { deckId: "1", track: { title: "Track", artist: "Artist" } });

    expect(tracks).toEqual(["Track"]);
  });
});

const plugin = new SeratoPlugin();
// @ts-expect-error plugin event names and payloads must match PluginEventMap
plugin.emit("track", { deckId: 1, track: null });
// @ts-expect-error plugins cannot emit undeclared events
plugin.emit("connected", {});
