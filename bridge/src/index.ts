/**
 * WrzDJ Bridge
 *
 * Connects to DJ equipment via a plugin system and reports track changes
 * to the WrzDJ backend.
 *
 * Environment variables:
 *   WRZDJ_API_URL           - Backend API URL (default: http://localhost:8000)
 *   WRZDJ_BRIDGE_API_KEY    - API key for authentication (required)
 *   WRZDJ_EVENT_CODE        - Event code to report tracks for (required)
 *   WRZDJ_PLUGIN            - Plugin to use (default: stagelinq)
 *   MIN_PLAY_SECONDS        - Debounce threshold in seconds (default: 5)
 *   LIVE_THRESHOLD_SECONDS  - Seconds before track is considered "live" (default: 15)
 *   PAUSE_GRACE_SECONDS     - Seconds of pause tolerated before resetting (default: 3)
 *   USE_FADER_DETECTION     - Require fader > 0 for live detection (default: false)
 *   MASTER_DECK_PRIORITY    - Only report from master deck (default: false)
 */
import { config, validateConfig } from "./config.js";
import {
  clearNowPlaying,
  getCircuitBreaker,
  getDetailedStatus,
  postBridgeStatus,
  postNowPlaying,
  shouldSkipTrack,
  updateLastTrack,
} from "./bridge.js";
import { CommandPoller } from "./command-poller.js";
import type { BridgeCommand } from "./command-poller.js";
import type { DeckLiveEvent } from "./deck-state.js";
import { Logger } from "./logger.js";
import { getPlugin } from "./plugin-registry.js";
import { PluginBridge } from "./plugin-bridge.js";
import type { PluginConnectionEvent } from "./plugin-types.js";

const log = new Logger("Bridge");

// Register built-in plugins
import "./plugins/index.js";

let pluginBridge: PluginBridge | null = null;
let commandPoller: CommandPoller | null = null;

/** Build enriched status fields for heartbeat/status posts. */
function buildEnrichedStatus(): ReturnType<typeof getDetailedStatus> & {
  plugin_id?: string;
  deck_count?: number;
} {
  const detailed = getDetailedStatus();
  return {
    ...detailed,
    plugin_id: pluginBridge?.pluginId,
    deck_count: pluginBridge?.manager.getDeckIds().length,
  };
}

async function main(): Promise<void> {
  log.info("WrzDJ Bridge starting...");

  // Validate configuration
  validateConfig();
  log.info(`API URL: ${config.apiUrl}`);
  log.info(`Event Code: ${config.eventCode}`);
  log.info(`Plugin: ${config.plugin}`);
  log.info(`Live Threshold: ${config.liveThresholdSeconds}s`);
  log.info(`Pause Grace: ${config.pauseGraceSeconds}s`);
  log.info(`Now Playing Pause: ${config.nowPlayingPauseSeconds}s`);
  log.info(`Min Play Seconds: ${config.minPlaySeconds}s`);
  log.info(`Fader Detection: ${config.useFaderDetection}`);
  log.info(`Master Deck Priority: ${config.masterDeckPriority}`);

  // Create the plugin
  const plugin = getPlugin(config.plugin);
  if (!plugin) {
    throw new Error(
      `Unknown plugin "${config.plugin}". Available plugins: stagelinq`
    );
  }

  // Create the plugin bridge
  pluginBridge = new PluginBridge(plugin, {
    liveThresholdSeconds: config.liveThresholdSeconds,
    pauseGraceSeconds: config.pauseGraceSeconds,
    nowPlayingPauseSeconds: config.nowPlayingPauseSeconds,
    useFaderDetection: config.useFaderDetection,
    masterDeckPriority: config.masterDeckPriority,
  });

  // Forward logs
  pluginBridge.on("log", (message: string) => {
    log.info(message);
  });

  // Handle track going "live"
  pluginBridge.on("deckLive", async (event: DeckLiveEvent) => {
    const { deckId, track } = event;

    if (shouldSkipTrack(track.artist, track.title)) {
      return;
    }

    log.info(`Deck ${deckId} LIVE: "${track.title}" by ${track.artist}`);

    updateLastTrack(track.artist, track.title);
    await postNowPlaying(track.title, track.artist, track.album, deckId, pluginBridge!.pluginId);
  });

  // Handle heartbeat — keep bridge_last_seen fresh on the backend
  pluginBridge.on("heartbeat", async () => {
    await postBridgeStatus(true, undefined, buildEnrichedStatus());
  });

  // Handle authoritative now-playing clear
  pluginBridge.on("clearNowPlaying", async () => {
    await clearNowPlaying();
  });

  // Handle connection status
  pluginBridge.on("connection", async (event: PluginConnectionEvent) => {
    if (event.connected) {
      log.info(`Device connected: ${event.deviceName}`);
      await postBridgeStatus(true, event.deviceName, buildEnrichedStatus());
    } else {
      log.info("Device disconnected");
      await postBridgeStatus(false);
    }
  });

  // Start command poller
  const cmdLog = log.child("CommandPoller");
  commandPoller = new CommandPoller(getCircuitBreaker(), cmdLog);

  commandPoller.on("command", async (commandType: string, command?: BridgeCommand) => {
    if (!pluginBridge) return;

    cmdLog.info(`Executing command: ${commandType}`);
    try {
      switch (commandType) {
        case "reset_decks":
          pluginBridge.resetDecks();
          break;
        case "reconnect":
          await pluginBridge.reconnect();
          break;
        case "restart":
          await pluginBridge.restart();
          break;
        case "setbuilder_transport":
          handleSetbuilderTransport(command?.payload ?? {});
          break;
        default:
          cmdLog.warn(`Unknown command type: ${commandType}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      cmdLog.error(`Command "${commandType}" failed: ${message}`);
    }
  });

  commandPoller.start(config.apiUrl, config.apiKey, config.eventCode);

  // Graceful shutdown
  const shutdown = async (signal: string): Promise<void> => {
    log.info(`Received ${signal}, shutting down...`);
    if (commandPoller) {
      commandPoller.stop();
    }
    if (pluginBridge) {
      await pluginBridge.stop();
    }
    await clearNowPlaying();
    await postBridgeStatus(false);
    process.exit(0);
  };

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  // Start the plugin bridge
  await pluginBridge.start();

  // Immediate handshake — tell the backend we're online and listening
  log.info("Bridge online — sending initial status to backend");
  await postBridgeStatus(true, undefined, buildEnrichedStatus());
}

function handleSetbuilderTransport(payload: Record<string, unknown>): void {
  const action = typeof payload.action === "string" ? payload.action : "unknown";
  const title = typeof payload.title === "string" ? payload.title : "";
  const position = typeof payload.position_sec === "number" ? payload.position_sec : 0;

  log.info(
    `Setbuilder transport command received: ${action}${title ? ` "${title}"` : ""} @ ${position.toFixed(1)}s`
  );
}

// Run the bridge
main().catch((err: Error) => {
  log.error(`Fatal error: ${err.message}`);
  if (commandPoller) {
    commandPoller.stop();
  }
  if (pluginBridge) {
    pluginBridge.stop().catch(() => {});
  }
  process.exit(1);
});
