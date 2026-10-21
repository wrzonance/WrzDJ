import { EventEmitter } from "events";
import type { DeckStateManagerConfig } from "../../deck/deck-state.js";
import type { PluginBridge } from "../../plugins/plugin-bridge.js";
import type { EquipmentSourcePlugin, PluginCapabilities } from "../../plugins/plugin-types.js";

export const DEFAULT_CONFIG: DeckStateManagerConfig = {
  liveThresholdSeconds: 15,
  pauseGraceSeconds: 3,
  nowPlayingPauseSeconds: 10,
  useFaderDetection: false,
  masterDeckPriority: false,
};

export const FULL_CAPABILITIES: PluginCapabilities = {
  multiDeck: true,
  playState: true,
  faderLevel: true,
  masterDeck: true,
  albumMetadata: true,
};

export const MINIMAL_CAPABILITIES: PluginCapabilities = {
  multiDeck: false,
  playState: false,
  faderLevel: false,
  masterDeck: false,
  albumMetadata: false,
};

export function createMockPlugin(
  capabilities: PluginCapabilities = FULL_CAPABILITIES
): EquipmentSourcePlugin {
  const emitter = new EventEmitter() as unknown as EquipmentSourcePlugin;
  let running = false;
  Object.defineProperty(emitter, "isRunning", { get: () => running });
  Object.assign(emitter, {
    info: { id: "mock", name: "Mock Plugin", description: "Test" },
    capabilities,
    configOptions: [],
    start: async () => {
      running = true;
    },
    stop: async () => {
      running = false;
    },
  });
  return emitter;
}

export function getDeckStateSnapshot(bridge: PluginBridge, deckId: string) {
  const state = bridge.getDeckStatusSnapshot().deckStates.find((deck) => deck.deckId === deckId);
  if (!state) throw new Error(`Deck ${deckId} is not tracked`);
  return state;
}
