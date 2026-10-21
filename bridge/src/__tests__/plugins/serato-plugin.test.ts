/**
 * Tests for Serato DJ Plugin
 *
 * Tests plugin lifecycle, metadata, event emission, and deduplication.
 * Uses temporary directories with hand-crafted binary session files.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { appendFileSync, mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { SeratoPlugin } from "../../plugins/serato-plugin.js";
import type { PluginTrackEvent, PluginConnectionEvent } from "../../plugins/plugin-types.js";
import {
  buildSeratoOentChunk as buildOentChunk,
  buildSeratoTextField as buildTextField,
  buildSeratoU32Field as buildU32Field,
} from "../fixtures/serato-binary.js";

function buildTrackChunk(
  title: string,
  artist: string,
  deck: number,
  album?: string
): Buffer {
  const fields = [
    buildTextField(2, title),
    buildTextField(6, artist),
    buildU32Field(52, deck),
  ];
  if (album) {
    fields.push(buildTextField(8, album));
  }
  return buildOentChunk(fields);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SeratoPlugin", () => {
  let plugin: SeratoPlugin;
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "serato-plugin-test-"));
    plugin = new SeratoPlugin();
  });

  afterEach(async () => {
    if (plugin?.isRunning) {
      await plugin.stop();
    }
    vi.useRealTimers();
    try {
      rmSync(tmpDir, { recursive: true });
    } catch {
      // cleanup best-effort
    }
  });

  async function startWithControlledPolling(): Promise<void> {
    vi.useFakeTimers();
    await plugin.start({ seratoPath: tmpDir, pollInterval: 200 });
  }

  async function pollOnce(): Promise<void> {
    await vi.advanceTimersByTimeAsync(200);
  }

  // -- Metadata --

  it("has correct metadata", () => {
    expect(plugin.info.id).toBe("serato");
    expect(plugin.info.name).toBe("Serato DJ");
  });

  it("has correct capabilities", () => {
    expect(plugin.capabilities.multiDeck).toBe(true);
    expect(plugin.capabilities.playState).toBe(false);
    expect(plugin.capabilities.faderLevel).toBe(false);
    expect(plugin.capabilities.masterDeck).toBe(false);
    expect(plugin.capabilities.albumMetadata).toBe(true);
  });

  it("exposes configOptions", () => {
    expect(plugin.configOptions).toHaveLength(2);

    const pathOpt = plugin.configOptions.find((o) => o.key === "seratoPath");
    expect(pathOpt).toMatchObject({ type: "string", default: "" });

    const pollOpt = plugin.configOptions.find((o) => o.key === "pollInterval");
    expect(pollOpt).toMatchObject({ type: "number", default: 1000, min: 200, max: 10000 });
  });

  // -- Lifecycle --

  it("starts and stops cleanly", async () => {
    expect(plugin.isRunning).toBe(false);

    await startWithControlledPolling();
    expect(plugin.isRunning).toBe(true);

    await plugin.stop();
    expect(plugin.isRunning).toBe(false);
  });

  it("throws when starting an already-running plugin", async () => {
    await startWithControlledPolling();
    await expect(
      plugin.start({ seratoPath: tmpDir, pollInterval: 200 })
    ).rejects.toThrow("already running");
  });

  it("stop is idempotent when not running", async () => {
    await plugin.stop(); // should not throw
  });

  it("rejects invalid pollInterval", async () => {
    await expect(
      plugin.start({ seratoPath: tmpDir, pollInterval: 50 })
    ).rejects.toThrow("Invalid pollInterval");
  });

  // -- Connection events --

  it("emits connection false when no session files exist", async () => {
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await startWithControlledPolling();
    // Give it a tick to process

    expect(connections.some((c) => c.connected === false)).toBe(true);
  });

  it("emits connection true when session file exists", async () => {
    // Create a session file
    writeFileSync(join(tmpDir, "test.session"), Buffer.alloc(0));

    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await startWithControlledPolling();

    expect(connections.some((c) => c.connected === true)).toBe(true);
    expect(
      connections.find((c) => c.connected === true)?.deviceName
    ).toBe("Serato DJ");
  });

  // -- Track events --

  it("emits track events when new bytes appear in session file", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Append a track entry
    const chunk = buildTrackChunk("Strobe", "Deadmau5", 1, "Random Album Title");
    writeFileSync(sessionFile, chunk);

    // Wait for poll
    await pollOnce();

    expect(tracks).toHaveLength(1);
    expect(tracks[0]!.track?.title).toBe("Strobe");
    expect(tracks[0]!.track?.artist).toBe("Deadmau5");
    expect(tracks[0]!.track?.album).toBe("Random Album Title");
    expect(tracks[0]!.deckId).toBe("1");
  });

  it("emits tracks on different decks", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Append two tracks on different decks
    const chunk1 = buildTrackChunk("Track A", "Artist A", 1);
    const chunk2 = buildTrackChunk("Track B", "Artist B", 2);
    writeFileSync(sessionFile, Buffer.concat([chunk1, chunk2]));

    await pollOnce();

    expect(tracks).toHaveLength(2);
    expect(tracks[0]!.deckId).toBe("1");
    expect(tracks[1]!.deckId).toBe("2");
  });

  it("deduplicates identical consecutive tracks on the same deck", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Write same track twice on deck 1
    const chunk1 = buildTrackChunk("Same Song", "Same Artist", 1);
    const chunk2 = buildTrackChunk("Same Song", "Same Artist", 1);
    writeFileSync(sessionFile, Buffer.concat([chunk1, chunk2]));

    await pollOnce();

    expect(tracks).toHaveLength(1);
  });

  it("does not deduplicate same track on different decks", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Same track on two different decks
    const chunk1 = buildTrackChunk("Same Song", "Same Artist", 1);
    const chunk2 = buildTrackChunk("Same Song", "Same Artist", 2);
    writeFileSync(sessionFile, Buffer.concat([chunk1, chunk2]));

    await pollOnce();

    expect(tracks).toHaveLength(2);
  });

  it("omits album field when not present", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    const chunk = buildTrackChunk("Title", "Artist", 1);
    writeFileSync(sessionFile, chunk);

    await pollOnce();

    expect(tracks).toHaveLength(1);
    expect(tracks[0]!.track?.album).toBeUndefined();
  });

  it("skips entries with no title and no artist", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Empty OENT — no title or artist fields
    const emptyChunk = buildOentChunk([buildU32Field(52, 1)]);
    const realChunk = buildTrackChunk("Real Track", "Real Artist", 1);
    writeFileSync(sessionFile, Buffer.concat([emptyChunk, realChunk]));

    await pollOnce();

    expect(tracks).toHaveLength(1);
    expect(tracks[0]!.track?.title).toBe("Real Track");
  });

  // -- Incremental file growth --

  it("detects incrementally appended tracks across poll cycles", async () => {
    const sessionFile = join(tmpDir, "test.session");
    // Start with one track already in the file
    const initialChunk = buildTrackChunk("Initial Song", "Initial Artist", 1);
    writeFileSync(sessionFile, initialChunk);

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();
    // Wait past first poll — initial track should NOT be emitted (offset starts at file end)
    await pollOnce();
    expect(tracks).toHaveLength(0);

    // Now append a new track (simulating Serato loading a new track)
    const newChunk = buildTrackChunk("New Song", "New Artist", 2);
    appendFileSync(sessionFile, newChunk);

    await pollOnce();

    expect(tracks).toHaveLength(1);
    expect(tracks[0]!.track?.title).toBe("New Song");
    expect(tracks[0]!.deckId).toBe("2");
  });

  it("allows re-emitting a track on the same deck after a different track", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Track A → Track B → Track A again on the same deck
    const chunkA = buildTrackChunk("Track A", "Artist", 1);
    const chunkB = buildTrackChunk("Track B", "Artist", 1);
    const chunkA2 = buildTrackChunk("Track A", "Artist", 1);
    writeFileSync(sessionFile, Buffer.concat([chunkA, chunkB, chunkA2]));

    await pollOnce();

    // All three should be emitted (A→B breaks dedup, B→A breaks dedup)
    expect(tracks).toHaveLength(3);
    expect(tracks[0]!.track?.title).toBe("Track A");
    expect(tracks[1]!.track?.title).toBe("Track B");
    expect(tracks[2]!.track?.title).toBe("Track A");
  });

  it("defaults deck to '1' when deck field is 0", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await startWithControlledPolling();

    // Track with deck=0 (no deck field set)
    const chunk = buildTrackChunk("No Deck", "Artist", 0);
    writeFileSync(sessionFile, chunk);

    await pollOnce();

    expect(tracks).toHaveLength(1);
    expect(tracks[0]!.deckId).toBe("1");
  });

  it("emits log events during operation", async () => {
    writeFileSync(join(tmpDir, "test.session"), Buffer.alloc(0));

    const logs: string[] = [];
    plugin.on("log", (msg: string) => logs.push(msg));

    await startWithControlledPolling();

    expect(logs.length).toBeGreaterThan(0);
    expect(logs.some((m) => m.includes("Watching session file"))).toBe(true);
  });

  it("rescans after 5 consecutive read errors", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const connections: PluginConnectionEvent[] = [];
    const logs: string[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));
    plugin.on("log", (msg: string) => logs.push(msg));

    await startWithControlledPolling();

    // Should be connected
    expect(connections.some((c) => c.connected === true)).toBe(true);

    // Append data so file has new bytes to read
    const chunk = buildTrackChunk("Track", "Artist", 1);
    appendFileSync(sessionFile, chunk);

    // Opening this directory succeeds, but reading it fails on every OS user.
    // Unlike chmod, this also works when the test process has elevated permissions.
    unlinkSync(sessionFile);
    mkdirSync(sessionFile);
    await vi.advanceTimersByTimeAsync(5 * 200);

    // Should have logged the rescan message and emitted connection:false
    expect(logs.some((m) => m.includes("rescanning"))).toBe(true);

    // A disconnect event should have been emitted during the rescan
    // (plugin may immediately reconnect if the file is still locatable)
    const connectionsAfterStart = connections.slice(1); // skip initial connect
    expect(connectionsAfterStart.some((c) => !c.connected)).toBe(true);

  });

  it("emits connection false when session file is deleted", async () => {
    const sessionFile = join(tmpDir, "test.session");
    writeFileSync(sessionFile, Buffer.alloc(0));

    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await startWithControlledPolling();

    // Should have connected
    expect(connections.some((c) => c.connected === true)).toBe(true);

    // Delete the session file
    unlinkSync(sessionFile);

    // Wait for poll to detect the deletion
    await pollOnce();

    expect(connections.some((c) => c.connected === false)).toBe(true);
  });
});
