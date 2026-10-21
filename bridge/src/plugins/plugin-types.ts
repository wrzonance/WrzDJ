/**
 * Plugin system types for WrzDJ Bridge.
 *
 * Each DJ software integration implements EquipmentSourcePlugin and emits
 * normalized events that PluginBridge translates into DeckStateManager calls.
 */
import type { TrackInfo } from "../shared/track-types.js";
import { EventArgumentMap, TypedEventEmitter } from "../shared/typed-event-emitter.js";

/** Declares what data a plugin can provide */
export interface PluginCapabilities {
  /** Plugin reports per-deck data (vs single combined stream) */
  readonly multiDeck: boolean;
  /** Plugin provides explicit play/pause state */
  readonly playState: boolean;
  /** Plugin provides channel fader levels */
  readonly faderLevel: boolean;
  /** Plugin provides master deck assignment */
  readonly masterDeck: boolean;
  /** Plugin provides album metadata */
  readonly albumMetadata: boolean;
}

/** Static metadata about a plugin */
export interface PluginInfo {
  readonly id: string;
  readonly name: string;
  readonly description: string;
}

/** Describes a user-configurable option exposed by a plugin */
export interface PluginConfigOption {
  readonly key: string;
  readonly label: string;
  readonly type: "number" | "string" | "boolean";
  readonly default: number | string | boolean;
  readonly description?: string;
  readonly min?: number;
  readonly max?: number;
}

/** Track event emitted by a plugin */
export interface PluginTrackEvent {
  readonly deckId: string;
  readonly track: TrackInfo | null;
}

/** Play state event emitted by a plugin */
export interface PluginPlayStateEvent {
  readonly deckId: string;
  readonly isPlaying: boolean;
}

/** Fader level event emitted by a plugin */
export interface PluginFaderEvent {
  readonly deckId: string;
  readonly level: number;
}

/** Master deck event emitted by a plugin */
export interface PluginMasterDeckEvent {
  readonly deckId: string;
}

/** Connection event emitted by a plugin */
export interface PluginConnectionEvent {
  readonly connected: boolean;
  readonly deviceName?: string;
}

/** Map of plugin event names to their payload types */
export interface PluginEventMap {
  track: PluginTrackEvent;
  playState: PluginPlayStateEvent;
  fader: PluginFaderEvent;
  masterDeck: PluginMasterDeckEvent;
  connection: PluginConnectionEvent;
  ready: void;
  log: string;
  error: Error;
}

/** Argument tuples used by the emitter while PluginEventMap remains the public payload map. */
export type PluginEventArguments = EventArgumentMap<PluginEventMap>;

/**
 * Common contract all equipment source plugins implement.
 *
 * Plugins extend EventEmitter and emit the events defined in PluginEventMap.
 * The PluginBridge listens to these events and translates them into
 * DeckStateManager calls, synthesizing missing data based on capabilities.
 */
export interface EquipmentSourcePlugin extends TypedEventEmitter<PluginEventArguments> {
  readonly info: PluginInfo;
  readonly capabilities: PluginCapabilities;
  readonly configOptions: readonly PluginConfigOption[];
  readonly isRunning: boolean;

  /** Start the plugin. Config is plugin-specific. */
  start(config?: Record<string, unknown>): Promise<void>;

  /** Stop the plugin and clean up resources. */
  stop(): Promise<void>;
}
