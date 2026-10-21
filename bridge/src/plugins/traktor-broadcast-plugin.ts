/**
 * Traktor Broadcast Equipment Source Plugin
 *
 * Receives track metadata from Traktor via its built-in broadcast feature.
 * Traktor broadcasts an Icecast-compatible stream with ICY metadata containing
 * "Artist - Title" in the StreamTitle field.
 *
 * Capabilities are minimal:
 *   - No multi-deck (single combined stream)
 *   - No play state (synthesized by PluginBridge from metadata changes)
 *   - No fader level
 *   - No master deck
 *   - No album metadata (Traktor only broadcasts artist + title)
 *
 * The user configures Traktor to broadcast to localhost:PORT. This plugin
 * runs an HTTP server that accepts the Icecast source connection and parses
 * ICY metadata embedded in the audio stream.
 *
 * References:
 *   - https://github.com/radusuciu/traktor_nowplaying
 *   - https://github.com/DiscoNova/traktor-metadata-samples
 */
import type { PluginMeta } from "./plugin-registry.js";
import { createServer, type IncomingMessage, type ServerResponse, type Server } from "http";
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";

import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConfigOption,
  PluginInfo,
  PluginEventMap,
  PluginEventArguments,
} from "./plugin-types.js";

const DEFAULT_PORT = 8123;
const MAX_PORT = 65_535;

/** Maximum ICY metadata block size (1024 * 16 = 16KB — far exceeds any real metadata). */
const MAX_ICY_META_LENGTH = 16_384;

/** Parse ICY StreamTitle value: "Artist - Title" → { artist, title } */
export function parseStreamTitle(raw: string): { artist: string; title: string } | null {
  if (!raw || !raw.trim()) return null;

  // Icecast format: StreamTitle='Artist - Title';
  const match = raw.match(/StreamTitle='(.*)'/);
  const content = match ? match[1] : raw;

  if (!content.trim()) return null;

  // Split on " - " (space-dash-space) which is the standard separator
  const sepIndex = content.indexOf(" - ");
  if (sepIndex === -1) {
    // No separator — treat entire string as title
    return { artist: "", title: content.trim() };
  }

  return {
    artist: content.substring(0, sepIndex).trim(),
    title: content.substring(sepIndex + 3).trim(),
  };
}

export class TraktorBroadcastPlugin extends TypedEventEmitter<PluginEventArguments> implements EquipmentSourcePlugin {
  static readonly metadata: PluginMeta = {
    info: {
      id: "traktor-broadcast",
      name: "Traktor Broadcast",
      description: "Receives track metadata from Traktor via broadcast stream",
    },
    capabilities: {
      multiDeck: false,
      playState: false,
      faderLevel: false,
      masterDeck: false,
      albumMetadata: false,
    },
    configOptions: [
      {
        key: "port",
        label: "Broadcast port",
        type: "number",
        default: DEFAULT_PORT,
        min: 0,
        max: 65535,
        description: "Local port for Traktor to broadcast to (0 selects an available port)",
      },
    ]
  };

  readonly info: PluginInfo = structuredClone(TraktorBroadcastPlugin.metadata.info);

  readonly capabilities: PluginCapabilities = structuredClone(TraktorBroadcastPlugin.metadata.capabilities);

  readonly configOptions: readonly PluginConfigOption[] = structuredClone(TraktorBroadcastPlugin.metadata.configOptions);

  private server: Server | null = null;
  private running = false;
  private port = DEFAULT_PORT;
  private lastStreamTitle: string | null = null;
  private readonly activeConnections = new Set<IncomingMessage>();

  get listeningPort(): number | null {
    const address = this.server?.address();
    return address && typeof address !== "string" ? address.port : null;
  }

  get isRunning(): boolean {
    return this.running;
  }

  async start(config?: Record<string, unknown>): Promise<void> {
    if (this.running) {
      throw new Error("Traktor Broadcast plugin is already running");
    }

    const port = config?.port === undefined ? DEFAULT_PORT : config.port;
    if (typeof port !== "number" || !Number.isInteger(port) || port < 0 || port > MAX_PORT) {
      throw new Error(`Invalid port: must be an integer between 0 and ${MAX_PORT}.`);
    }
    this.port = port;
    this.running = true;
    this.lastStreamTitle = null;

    try {
      await this.startServer();
    } catch (error) {
      // A bind failure happens before the plugin owns a listening server. Roll
      // back the startup state so callers can correct the port and retry.
      this.running = false;
      this.lastStreamTitle = null;
      this.server = null;
      throw error;
    }
  }

  async stop(): Promise<void> {
    if (!this.running) return;

    this.running = false;
    this.lastStreamTitle = null;

    // Destroy tracked request streams before closing server
    for (const req of this.activeConnections) {
      req.destroy();
    }
    this.activeConnections.clear();

    const server = this.server;
    if (server) {
      this.server = null;
      // Force-close all open connections (streaming connections never end naturally)
      server.closeAllConnections();
      await new Promise<void>((resolve) => {
        server.close(() => resolve());
      });
    }

    this.removeAllListeners();
  }

  private async startServer(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      let started = false;

      this.server = createServer((req: IncomingMessage, res: ServerResponse) => {
        this.handleRequest(req, res);
      });

      this.server.on("error", (err: Error) => {
        this.emit("log", `Server error: ${err.message}`);
        if (!started) {
          reject(err);
        } else {
          this.emit("error", err);
        }
      });

      this.server.listen(this.port, "127.0.0.1", () => {
        started = true;
        this.emit("log", `Listening on 127.0.0.1:${this.port} for Traktor broadcast`);
        this.emit("log", `Configure Traktor: Settings → Broadcasting → Address: 127.0.0.1, Port: ${this.port}`);
        resolve();
      });
    });
  }

  private handleRequest(req: IncomingMessage, res: ServerResponse): void {
    // Traktor sends a PUT/SOURCE request when starting broadcast
    this.emit("log", `Incoming connection: ${req.method} ${req.url}`);
    this.emit("connection", { connected: true, deviceName: "Traktor" });

    this.activeConnections.add(req);

    // Request ICY metadata from the source
    const icyMetaIntHeader = req.headers["icy-metaint"];
    const icyMetaInt = typeof icyMetaIntHeader === "string"
      ? Number.parseInt(icyMetaIntHeader, 10) || 0
      : 0;

    if (icyMetaInt > 0) {
      this.emit("log", `ICY metadata interval: ${icyMetaInt} bytes`);
      this.handleIcyStream(req, icyMetaInt);
    } else {
      // Fallback: look for metadata in headers or query params
      this.handleHeaderMetadata(req);
    }

    // Keep the connection alive — Traktor streams continuously
    res.writeHead(200, { "icy-metaint": "0" });
    res.flushHeaders();

    req.on("close", () => {
      this.activeConnections.delete(req);
      this.emit("log", "Traktor broadcast disconnected");
      this.emit("connection", { connected: false });
    });

    req.on("error", () => {
      this.activeConnections.delete(req);
      this.emit("log", "Traktor broadcast stream error");
      this.emit("connection", { connected: false });
    });
  }

  private handleIcyStream(req: IncomingMessage, metaInt: number): void {
    let byteCount = 0;
    let metaBuffer = Buffer.alloc(0);
    let readingMeta = false;
    let metaLength = 0;

    req.on("data", (chunk: Buffer) => {
      let pos = 0;

      while (pos < chunk.length) {
        if (readingMeta) {
          // Reading metadata bytes
          const remaining = metaLength - metaBuffer.length;
          const slice = chunk.subarray(pos, pos + remaining);
          metaBuffer = Buffer.concat([metaBuffer, slice]);
          pos += slice.length;

          if (metaBuffer.length >= metaLength) {
            // Complete metadata block
            const metadata = metaBuffer.toString("utf-8").replace(/\0+$/, "");
            if (metadata) {
              this.publishTrackMetadataIfChanged(metadata);
            }
            readingMeta = false;
            metaBuffer = Buffer.alloc(0);
            byteCount = 0;
          }
        } else {
          // Reading audio data — count bytes until metadata boundary
          const bytesUntilMeta = metaInt - byteCount;
          const audioBytes = Math.min(bytesUntilMeta, chunk.length - pos);
          pos += audioBytes;
          byteCount += audioBytes;

          if (byteCount >= metaInt) {
            // At metadata boundary — next byte is the length prefix
            if (pos < chunk.length) {
              const lengthByte = chunk[pos] ?? 0;
              pos += 1;
              metaLength = lengthByte * 16;

              if (metaLength === 0) {
                // No metadata this interval
                byteCount = 0;
              } else if (metaLength > MAX_ICY_META_LENGTH) {
                // Malformed stream — skip this metadata block
                this.emit("log", `ICY metadata length ${metaLength} exceeds maximum (${MAX_ICY_META_LENGTH}), skipping`);
                metaLength = 0;
                byteCount = 0;
              } else {
                readingMeta = true;
                metaBuffer = Buffer.alloc(0);
              }
            }
          }
        }
      }
    });
  }

  private handleHeaderMetadata(req: IncomingMessage): void {
    // Some configurations send metadata via ICY headers
    const icyNameHeader = req.headers["icy-name"];
    const icyName = typeof icyNameHeader === "string" ? icyNameHeader : undefined;
    if (icyName) {
      this.emit("log", `ICY name: ${icyName}`);
    }

    // Also watch for data chunks that might contain metadata text
    req.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf-8");
      if (text.includes("StreamTitle=")) {
        this.publishTrackMetadataIfChanged(text);
      }
    });
  }

  private publishTrackMetadataIfChanged(raw: string): void {
    const parsed = parseStreamTitle(raw);
    if (!parsed) return;

    const streamKey = `${parsed.artist}::${parsed.title}`;
    if (streamKey === this.lastStreamTitle) return;

    this.lastStreamTitle = streamKey;
    this.emit("log", `Track metadata: "${parsed.title}" by ${parsed.artist}`);

    this.emit("track", {
      deckId: "1",
      track: {
        title: parsed.title,
        artist: parsed.artist,
      },
    });
  }
}
