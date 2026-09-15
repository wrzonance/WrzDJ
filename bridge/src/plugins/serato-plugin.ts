/**
 * Serato DJ Equipment Source Plugin
 *
 * Watches Serato's binary session files for new track entries. When Serato
 * loads a track to a deck, it appends an OENT/ADAT chunk to the active
 * session file. This plugin polls the file for growth and parses new bytes
 * to extract track metadata.
 *
 * Capabilities are limited (like Traktor Broadcast):
 *   - Multi-deck: yes (session files include deck numbers)
 *   - Play state: no (can only detect "track loaded", not play/pause)
 *   - Fader level / master deck: no
 *   - Album metadata: yes (session files include album field)
 *
 * No npm dependencies — uses only Node.js built-ins + the session parser.
 *
 * References:
 *   - https://github.com/bkstein/SSL-API (Java, MIT)
 *   - https://github.com/whatsnowplaying/whats-now-playing (Python, MIT)
 */
import { EventEmitter } from "events";
import { closeSync, fstatSync, openSync, readSync, statSync, watch, type FSWatcher } from "fs";

function isMissingFileError(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as NodeJS.ErrnoException).code === "ENOENT";
}

import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConfigOption,
  PluginInfo,
} from "../plugin-types.js";
import {
  findLatestSessionFile,
  getDefaultSeratoPath,
  parseSessionBytes,
  type ParseResult,
  type SeratoTrackEntry,
} from "./serato-session-parser.js";

const DEFAULT_POLL_INTERVAL = 1000;

export class SeratoPlugin extends EventEmitter implements EquipmentSourcePlugin {
  readonly info: PluginInfo = {
    id: "serato",
    name: "Serato DJ",
    description: "Watches Serato session files for track metadata",
  };

  readonly capabilities: PluginCapabilities = {
    multiDeck: true,
    playState: false,
    faderLevel: false,
    masterDeck: false,
    albumMetadata: true,
  };

  readonly configOptions: readonly PluginConfigOption[] = [
    {
      key: "seratoPath",
      label: "Sessions folder",
      type: "string",
      default: "",
      description: "Path to Serato sessions folder (auto-detected if empty)",
    },
    {
      key: "pollInterval",
      label: "Poll interval (ms)",
      type: "number",
      default: DEFAULT_POLL_INTERVAL,
      min: 200,
      max: 10000,
      description: "How often to check for new track data",
    },
  ];

  private running = false;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private dirWatcher: FSWatcher | null = null;
  private sessionPath: string | null = null;
  private fileOffset = 0;
  private lastTrackPerDeck: Map<string, string> = new Map();
  private sessionsDir = "";
  private pollInterval = DEFAULT_POLL_INTERVAL;
  private consecutiveReadErrors = 0;

  get isRunning(): boolean {
    return this.running;
  }

  async start(config?: Record<string, unknown>): Promise<void> {
    if (this.running) {
      throw new Error("Serato plugin is already running");
    }

    const seratoPath = (config?.seratoPath as string) || "";
    this.sessionsDir = seratoPath || getDefaultSeratoPath();
    this.pollInterval =
      (config?.pollInterval as number) ?? DEFAULT_POLL_INTERVAL;

    if (
      !Number.isInteger(this.pollInterval) ||
      this.pollInterval < 200 ||
      this.pollInterval > 10000
    ) {
      throw new Error(
        `Invalid pollInterval: ${this.pollInterval}. Must be an integer between 200 and 10000.`
      );
    }

    this.running = true;
    this.fileOffset = 0;
    this.lastTrackPerDeck = new Map();
    this.sessionPath = null;

    this.emit("log", `Looking for Serato session files in: ${this.sessionsDir}`);
    this.locateSessionFile();
    this.startPolling();
    this.watchForNewSessions();
  }

  async stop(): Promise<void> {
    if (!this.running) return;

    this.running = false;

    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }

    if (this.dirWatcher !== null) {
      this.dirWatcher.close();
      this.dirWatcher = null;
    }

    this.sessionPath = null;
    this.fileOffset = 0;
    this.lastTrackPerDeck = new Map();

    this.removeAllListeners();
  }

  /** Find the latest session file and start reading from the end. */
  private locateSessionFile(): void {
    const sessionFile = findLatestSessionFile(this.sessionsDir);

    if (!sessionFile) {
      this.emit("log", "No Serato session files found yet");
      this.emit("connection", { connected: false });
      return;
    }

    this.sessionPath = sessionFile;

    // Start from the end of the file — we only want new entries
    try {
      const stat = statSync(sessionFile);
      this.fileOffset = stat.size;
    } catch {
      this.fileOffset = 0;
    }

    this.emit("log", `Watching session file: ${sessionFile}`);
    this.emit("connection", { connected: true, deviceName: "Serato DJ" });
  }

  /** Poll the session file for new bytes. */
  private startPolling(): void {
    this.pollTimer = setInterval(() => {
      if (!this.running) return;
      this.pollSessionFile();
    }, this.pollInterval);
  }

  /** Watch the sessions directory for new session files. */
  private watchForNewSessions(): void {
    try {
      this.dirWatcher = watch(this.sessionsDir, (eventType, filename) => {
        if (!this.running) return;
        if (!filename?.endsWith(".session")) return;

        // A new session file appeared — switch to it
        const newSession = findLatestSessionFile(this.sessionsDir);
        if (newSession && newSession !== this.sessionPath) {
          this.emit("log", `New session file detected: ${newSession}`);
          this.sessionPath = newSession;
          this.fileOffset = 0;
          this.lastTrackPerDeck = new Map();
          this.emit("connection", { connected: true, deviceName: "Serato DJ" });
        }
      });
    } catch {
      this.emit("log", "Could not watch sessions directory — will rely on polling");
    }
  }

  /** Read new bytes from the session file and parse them. */
  private pollSessionFile(): void {
    if (!this.sessionPath) {
      // Try to find a session file if we don't have one yet
      this.locateSessionFile();
      return;
    }

    // Open once and fstat/read through the same descriptor: sizing the read
    // from a separate stat() would be a check-then-act race against Serato's
    // writer (CodeQL js/file-system-race). Only the bytes past fileOffset are
    // read, so a growing session file is not re-read from the start each poll.
    let fd: number;
    try {
      fd = openSync(this.sessionPath, "r");
    } catch (err) {
      if (isMissingFileError(err)) {
        // File was deleted or rotated — try to find a new one
        this.sessionPath = null;
        this.emit("connection", { connected: false });
        return;
      }
      this.recordReadError(err);
      return;
    }

    let newBytes: Buffer;
    try {
      const fileSize = fstatSync(fd).size;
      if (fileSize <= this.fileOffset) return;
      const length = fileSize - this.fileOffset;
      const buffer = Buffer.alloc(length);
      const bytesRead = readSync(fd, buffer, 0, length, this.fileOffset);
      newBytes = buffer.subarray(0, bytesRead);
    } catch (err) {
      this.recordReadError(err);
      return;
    } finally {
      closeSync(fd);
    }

    this.consecutiveReadErrors = 0;

    // Parse new entries — only advance fileOffset by fully consumed bytes
    // so incomplete chunks (Serato mid-write) are re-read on next poll
    const result: ParseResult = parseSessionBytes(newBytes);
    this.fileOffset += result.bytesConsumed;

    for (const entry of result.entries) {
      this.processEntry(entry);
    }
  }

  /** Count a failed read; after five in a row, drop the file and rescan. */
  private recordReadError(err: unknown): void {
    const message = err instanceof Error ? err.message : String(err);
    this.emit("log", `Error reading session file: ${message}`);
    this.consecutiveReadErrors += 1;
    if (this.consecutiveReadErrors >= 5) {
      this.emit("log", `Session file unreadable after ${this.consecutiveReadErrors} attempts — rescanning`);
      this.sessionPath = null;
      this.fileOffset = 0;
      this.consecutiveReadErrors = 0;
      this.emit("connection", { connected: false });
    }
  }

  /** Process a parsed track entry, deduplicating per deck. */
  private processEntry(entry: SeratoTrackEntry): void {
    if (!entry.title && !entry.artist) return;

    const deckId = String(entry.deck || 1);
    const trackKey = `${entry.artist}::${entry.title}`;

    if (this.lastTrackPerDeck.get(deckId) === trackKey) return;

    this.lastTrackPerDeck.set(deckId, trackKey);
    this.emit("log", `Deck ${deckId}: "${entry.title}" by ${entry.artist}`);

    this.emit("track", {
      deckId,
      track: {
        title: entry.title,
        artist: entry.artist,
        ...(entry.album ? { album: entry.album } : {}),
      },
    });
  }
}
