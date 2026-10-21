import type { DeckStateManagerConfig } from "../deck/deck-state.js";

/** Bridge configuration is read and validated explicitly at startup. */
export interface BridgeConfig {
  readonly apiUrl: string;
  readonly apiKey: string;
  readonly eventCode: string;
  readonly plugin: string;
  readonly minPlaySeconds: number;
  readonly liveThresholdSeconds: number;
  readonly nowPlayingPauseSeconds: number;
  readonly pauseGraceSeconds: number;
  readonly useFaderDetection: boolean;
  readonly masterDeckPriority: boolean;
}

/** Map orchestration settings to the narrower deck-state adapter contract. */
export function toDeckStateManagerConfig(config: BridgeConfig): DeckStateManagerConfig {
  return {
    liveThresholdSeconds: config.liveThresholdSeconds,
    pauseGraceSeconds: config.pauseGraceSeconds,
    nowPlayingPauseSeconds: config.nowPlayingPauseSeconds,
    useFaderDetection: config.useFaderDetection,
    masterDeckPriority: config.masterDeckPriority,
  };
}

function seconds(env: NodeJS.ProcessEnv, key: string, fallback: number): number {
  const value = Number(env[key] || fallback);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${key} must be a non-negative finite number`);
  }
  return value;
}

function validateApiUrl(apiUrl: string): void {
  let url: URL;
  try {
    url = new URL(apiUrl);
  } catch {
    throw new Error("WRZDJ_API_URL must be an absolute HTTP or HTTPS URL");
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("WRZDJ_API_URL must be an absolute HTTP or HTTPS URL");
  }
  const isLocalhost = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.protocol === "http:" && !isLocalhost) {
    console.warn(
      "[Bridge] WARNING: Using HTTP with a remote server. " +
      "Consider using HTTPS for production deployments to protect API keys."
    );
  }
}

/** Capture one validated configuration without changing the supplied environment. */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): BridgeConfig {
  const apiKey = env.WRZDJ_BRIDGE_API_KEY || "";
  const eventCode = env.WRZDJ_EVENT_CODE || "";
  if (!apiKey) {
    throw new Error("WRZDJ_BRIDGE_API_KEY is required. Generate one with: openssl rand -hex 32");
  }
  if (!eventCode) {
    throw new Error("WRZDJ_EVENT_CODE is required. This is the event code from the DJ dashboard.");
  }
  const apiUrl = env.WRZDJ_API_URL || "http://localhost:8000";
  validateApiUrl(apiUrl);

  return {
    apiUrl,
    apiKey,
    eventCode,
    plugin: env.WRZDJ_PLUGIN || "stagelinq",
    minPlaySeconds: seconds(env, "MIN_PLAY_SECONDS", 5),
    liveThresholdSeconds: seconds(env, "LIVE_THRESHOLD_SECONDS", 15),
    nowPlayingPauseSeconds: seconds(env, "NOW_PLAYING_PAUSE_SECONDS", 10),
    pauseGraceSeconds: seconds(env, "PAUSE_GRACE_SECONDS", 3),
    useFaderDetection: env.USE_FADER_DETECTION === "true",
    masterDeckPriority: env.MASTER_DECK_PRIORITY === "true",
  };
}
