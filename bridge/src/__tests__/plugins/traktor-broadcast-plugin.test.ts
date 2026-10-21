/**
 * Tests for Traktor Broadcast Plugin
 *
 * Tests ICY metadata parsing, StreamTitle parsing, and plugin lifecycle.
 */
import http from "http";
import { describe, it, expect, afterEach, vi } from "vitest";
import { TraktorBroadcastPlugin } from "../../plugins/traktor-broadcast-plugin.js";
import type { PluginTrackEvent, PluginConnectionEvent } from "../../plugins/plugin-types.js";

/** Helper to get the dynamically assigned port from the plugin's public status. */
function getPort(plugin: TraktorBroadcastPlugin): number {
  const port = plugin.listeningPort;
  if (port === null) throw new Error("Traktor server is not listening");
  return port;
}

function openStream(
  plugin: TraktorBroadcastPlugin,
  body?: string | Buffer,
  options: { readonly method?: string; readonly headers?: Record<string, string> } = {},
): Promise<() => void> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const request = http.request({
      hostname: "127.0.0.1",
      port: getPort(plugin),
      path: "/",
      method: options.method ?? "PUT",
      headers: { "Content-Type": "audio/mpeg", ...options.headers },
    }, (response) => {
      if (response.statusCode !== 200) {
        settled = true;
        reject(new Error(`Unexpected Traktor response status ${response.statusCode}`));
        request.destroy();
        return;
      }
      settled = true;
      resolve(() => request.destroy());
    });
    request.on("error", (error) => {
      if (!settled) reject(error);
    });
    if (body === undefined) request.flushHeaders();
    else request.write(body);
  });
}

function waitForConnection(plugin: TraktorBroadcastPlugin, connected: boolean): Promise<void> {
  return new Promise((resolve) => {
    const listener = (event: PluginConnectionEvent) => {
      if (event.connected !== connected) return;
      plugin.off("connection", listener);
      resolve();
    };
    plugin.on("connection", listener);
  });
}

describe("TraktorBroadcastPlugin", () => {
  let plugin: TraktorBroadcastPlugin;

  afterEach(async () => {
    if (plugin?.isRunning) {
      await plugin.stop();
    }
  });

  it("has correct metadata", () => {
    plugin = new TraktorBroadcastPlugin();
    expect(plugin.info.id).toBe("traktor-broadcast");
    expect(plugin.capabilities.multiDeck).toBe(false);
    expect(plugin.capabilities.playState).toBe(false);
    expect(plugin.capabilities.faderLevel).toBe(false);
    expect(plugin.capabilities.masterDeck).toBe(false);
    expect(plugin.capabilities.albumMetadata).toBe(false);
  });

  it("exposes configOptions with port option", () => {
    plugin = new TraktorBroadcastPlugin();
    expect(plugin.configOptions).toHaveLength(1);
    const portOpt = plugin.configOptions[0];
    expect(portOpt.key).toBe("port");
    expect(portOpt.type).toBe("number");
    expect(portOpt.default).toBe(8123);
    expect(portOpt.min).toBe(0); // Port 0 requests an available port from the OS.
    expect(portOpt.max).toBe(65535);
  });

  it("starts and stops cleanly", async () => {
    plugin = new TraktorBroadcastPlugin();
    expect(plugin.isRunning).toBe(false);
    expect(plugin.listeningPort).toBeNull();

    await plugin.start({ port: 0 });
    expect(plugin.isRunning).toBe(true);
    expect(plugin.listeningPort).toBeTypeOf("number");

    await plugin.stop();
    expect(plugin.isRunning).toBe(false);
    expect(plugin.listeningPort).toBeNull();
  });

  it("throws when starting an already-running plugin", async () => {
    plugin = new TraktorBroadcastPlugin();
    await plugin.start({ port: 0 });
    await expect(plugin.start({ port: 0 })).rejects.toThrow("already running");
  });

  it("clears failed listen state and can retry on the same port", async () => {
    // Regression for baseline 57cfcdc6867f: a bind failure left the plugin marked running.
    plugin = new TraktorBroadcastPlugin();
    const blocker = http.createServer();
    await new Promise<void>((resolve, reject) => {
      blocker.once("error", reject);
      blocker.listen(0, "127.0.0.1", resolve);
    });
    const address = blocker.address();
    if (!address || typeof address === "string") throw new Error("Blocker did not bind a TCP port");

    try {
      await expect(plugin.start({ port: address.port })).rejects.toMatchObject({ code: "EADDRINUSE" });
      expect(plugin.isRunning).toBe(false);
      expect(plugin.listeningPort).toBeNull();
      await plugin.stop();

      await new Promise<void>((resolve, reject) => {
        blocker.close((error) => error ? reject(error) : resolve());
      });
      await plugin.start({ port: address.port });
      expect(plugin.isRunning).toBe(true);
      expect(plugin.listeningPort).toBe(address.port);
      await plugin.stop();
      expect(plugin.isRunning).toBe(false);
      expect(plugin.listeningPort).toBeNull();
    } finally {
      if (plugin.isRunning) await plugin.stop();
      if (blocker.listening) {
        await new Promise<void>((resolve) => blocker.close(() => resolve()));
      }
    }
  });

  it("stop is idempotent when not running", async () => {
    plugin = new TraktorBroadcastPlugin();
    await plugin.stop();
  });

  it("emits connection event on incoming request", async () => {
    plugin = new TraktorBroadcastPlugin();
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await plugin.start({ port: 0 });
    try {
      const abort = await openStream(plugin, "StreamTitle='Deadmau5 - Strobe';");
      await vi.waitFor(() => expect(connections.some((event) => event.connected)).toBe(true));
      abort();
    } finally {
      await plugin.stop();
    }

    expect(connections.length).toBeGreaterThanOrEqual(1);
    expect(connections[0].connected).toBe(true);
  });

  it("emits track events when metadata is received", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await plugin.start({ port: 0 });
    try {
      const abort = await openStream(plugin, "StreamTitle='Deadmau5 - Strobe';");
      await vi.waitFor(() => expect(tracks).toHaveLength(1));
      abort();
    } finally {
      await plugin.stop();
    }

    expect(tracks).toHaveLength(1);
    expect(tracks[0].track?.title).toBe("Strobe");
    expect(tracks[0].track?.artist).toBe("Deadmau5");
    expect(tracks[0].deckId).toBe("1");
  });

  it("emits disconnection when stop closes an active connection", async () => {
    plugin = new TraktorBroadcastPlugin();
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (event) => connections.push(event));
    await plugin.start({ port: 0 });

    await openStream(plugin, "StreamTitle='Test - Track';");

    await plugin.stop();
    await vi.waitFor(() => expect(connections.some((event) => !event.connected)).toBe(true));
  });

  it("deduplicates identical consecutive tracks", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await plugin.start({ port: 0 });

    // Send same metadata twice in separate requests
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (event) => connections.push(event));
    try {
      let disconnected = waitForConnection(plugin, false);
      const abortFirst = await openStream(plugin, "StreamTitle='Artist - Song';");
      abortFirst();
      await disconnected;

      disconnected = waitForConnection(plugin, false);
      const abortSecond = await openStream(plugin, "StreamTitle='Artist - Song';");
      abortSecond();
      await disconnected;
    } finally {
      await plugin.stop();
    }

    expect(tracks).toHaveLength(1);
  });

  it("emits different track when metadata changes", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await plugin.start({ port: 0 });
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (event) => connections.push(event));
    try {
      let disconnected = waitForConnection(plugin, false);
      const abortFirst = await openStream(plugin, "StreamTitle='Artist A - Song One';");
      abortFirst();
      await disconnected;

      disconnected = waitForConnection(plugin, false);
      const abortSecond = await openStream(plugin, "StreamTitle='Artist B - Song Two';");
      abortSecond();
      await disconnected;
    } finally {
      await plugin.stop();
    }

    expect(tracks).toHaveLength(2);
    expect(tracks[0].track?.title).toBe("Song One");
    expect(tracks[1].track?.title).toBe("Song Two");
  });

  it("emits disconnect event when connection closes", async () => {
    plugin = new TraktorBroadcastPlugin();
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await plugin.start({ port: 0 });
    try {
      const abort = await openStream(plugin, "StreamTitle='Artist - Track';");
      abort();
      await vi.waitFor(() => expect(connections.some((event) => !event.connected)).toBe(true));
    } finally {
      await plugin.stop();
    }

    // Should have connected:true followed by connected:false
    expect(connections.some((c) => c.connected === true)).toBe(true);
    expect(connections.some((c) => c.connected === false)).toBe(true);
  });

  it("handles malformed metadata without crashing", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    const connections: PluginConnectionEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));
    plugin.on("connection", (event) => connections.push(event));

    await plugin.start({ port: 0 });
    try {
      const abort = await openStream(plugin, "StreamTitle='';");
      abort();
      await vi.waitFor(() => expect(connections.some((event) => !event.connected)).toBe(true));
    } finally {
      await plugin.stop();
    }

    expect(tracks).toHaveLength(0);
  });

  it("handles GET requests without crashing", async () => {
    plugin = new TraktorBroadcastPlugin();
    const connections: PluginConnectionEvent[] = [];
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await plugin.start({ port: 0 });
    // GET request (not typical Traktor behavior, but should not crash)
    try {
      const abort = await openStream(plugin, undefined, { method: "GET" });
      await vi.waitFor(() => expect(connections.some((event) => event.connected)).toBe(true));
      abort();
    } finally {
      await plugin.stop();
    }
    // Should still emit a connection event
    expect(connections.length).toBeGreaterThanOrEqual(1);
  });

  it("throws on invalid port configuration", async () => {
    plugin = new TraktorBroadcastPlugin();
    await expect(plugin.start({ port: -1 })).rejects.toThrow("Invalid port");
    await expect(plugin.start({ port: 99999 })).rejects.toThrow("Invalid port");
  });

  it("parses ICY metadata from binary stream with icy-metaint header", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await plugin.start({ port: 0 });

    // Build a proper ICY binary stream:
    // [metaInt bytes of audio] [1 byte length prefix] [metadata padded to 16 * lengthByte]
    const metaInt = 32; // small interval for testing
    const metadataStr = "StreamTitle='ICY Artist - ICY Track';";
    const metaLengthByte = Math.ceil(metadataStr.length / 16);
    const paddedLength = metaLengthByte * 16;
    const metadataBuf = Buffer.alloc(paddedLength);
    metadataBuf.write(metadataStr, "utf-8");

    // audio data (32 bytes of silence) + length prefix + metadata
    const audioBuf = Buffer.alloc(metaInt);
    const lengthBuf = Buffer.from([metaLengthByte]);
    const payload = Buffer.concat([audioBuf, lengthBuf, metadataBuf]);

    const closeStream = await openStream(plugin, payload, { headers: { "icy-metaint": String(metaInt) } });
    await vi.waitFor(() => expect(tracks).toHaveLength(1));
    closeStream();

    expect(tracks).toHaveLength(1);
    expect(tracks[0].track?.artist).toBe("ICY Artist");
    expect(tracks[0].track?.title).toBe("ICY Track");
  });

  it("handles ICY stream with zero-length metadata block", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await plugin.start({ port: 0 });

    const metaInt = 16;
    // audio data (16 bytes) + length prefix 0 (no metadata) + more audio (16 bytes) + length prefix + actual metadata
    const metadataStr = "StreamTitle='Zero Test Artist - Zero Test Track';";
    const metaLengthByte = Math.ceil(metadataStr.length / 16);
    const paddedLength = metaLengthByte * 16;
    const metadataBuf = Buffer.alloc(paddedLength);
    metadataBuf.write(metadataStr, "utf-8");

    const audioPart1 = Buffer.alloc(metaInt);
    const zeroLengthByte = Buffer.from([0]); // no metadata this interval
    const audioPart2 = Buffer.alloc(metaInt);
    const realLengthByte = Buffer.from([metaLengthByte]);
    const payload = Buffer.concat([audioPart1, zeroLengthByte, audioPart2, realLengthByte, metadataBuf]);

    const closeStream = await openStream(plugin, payload, { headers: { "icy-metaint": String(metaInt) } });
    await vi.waitFor(() => expect(tracks).toHaveLength(1));
    closeStream();

    expect(tracks).toHaveLength(1);
    expect(tracks[0].track?.title).toBe("Zero Test Track");
  });

  it("handles multiple ICY metadata updates in one connection", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

    await plugin.start({ port: 0 });
    const metaInt = 16;

    function buildIcyBlock(metadataStr: string): Buffer {
      const metaLengthByte = Math.ceil(metadataStr.length / 16);
      const paddedLength = metaLengthByte * 16;
      const metadataBuf = Buffer.alloc(paddedLength);
      metadataBuf.write(metadataStr, "utf-8");
      const audioBuf = Buffer.alloc(metaInt);
      const lengthBuf = Buffer.from([metaLengthByte]);
      return Buffer.concat([audioBuf, lengthBuf, metadataBuf]);
    }

    const block1 = buildIcyBlock("StreamTitle='DJ A - Track One';");
    const block2 = buildIcyBlock("StreamTitle='DJ B - Track Two';");
    const payload = Buffer.concat([block1, block2]);

    const closeStream = await openStream(plugin, payload, { headers: { "icy-metaint": String(metaInt) } });
    await vi.waitFor(() => expect(tracks).toHaveLength(2));
    closeStream();

    expect(tracks).toHaveLength(2);
    expect(tracks[0].track?.title).toBe("Track One");
    expect(tracks[1].track?.title).toBe("Track Two");
  });

  it("cascade: connect → metadata → disconnect → reconnect → new metadata", async () => {
    plugin = new TraktorBroadcastPlugin();
    const tracks: PluginTrackEvent[] = [];
    const connections: PluginConnectionEvent[] = [];
    plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));
    plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

    await plugin.start({ port: 0 });
    let disconnected = waitForConnection(plugin, false);
    try {
      const abortFirst = await openStream(plugin, "StreamTitle='First Artist - First Track';");
      await vi.waitFor(() => expect(tracks).toHaveLength(1));
      abortFirst();
      await disconnected;

      disconnected = waitForConnection(plugin, false);
      const abortSecond = await openStream(plugin, "StreamTitle='Second Artist - Second Track';");
      await vi.waitFor(() => expect(tracks).toHaveLength(2));
      abortSecond();
      await disconnected;
    } finally {
      await plugin.stop();
    }

    // Should have two track events from the full lifecycle
    expect(tracks).toHaveLength(2);
    expect(tracks[0].track?.artist).toBe("First Artist");
    expect(tracks[1].track?.artist).toBe("Second Artist");

    // Should have multiple connection events (connect, disconnect, connect)
    const connectEvents = connections.filter((c) => c.connected);
    const disconnectEvents = connections.filter((c) => !c.connected);
    expect(connectEvents.length).toBeGreaterThanOrEqual(2);
    expect(disconnectEvents.length).toBeGreaterThanOrEqual(1);
  });
});
