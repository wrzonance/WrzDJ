/**
 * Type declarations for stagelinq library
 *
 * The official types are incomplete - this extends them with the events
 * that are actually emitted at runtime.
 */
declare module "stagelinq" {
  import { EventEmitter } from "events";

  interface DeviceInfo {
    software?: { name?: string; version?: string };
    address?: string;
  }

  interface NowPlayingStatus {
    title?: string;
    artist?: string;
    album?: string;
    /** Deck identifier formatted as "{player}{layer}" e.g. "1A", "2B" */
    deck?: string;
    /** Player number (1-4) as configured on the hardware */
    player?: number;
    /** Layer letter: "A", "B", "C", or "D" */
    layer?: string;
    /** Explicit play state from Engine/Deck/Play */
    play?: boolean;
    /** Alternative play state from Engine/Deck/PlayState */
    playState?: boolean;
    /** Master deck status */
    masterStatus?: boolean;
    /** External mixer volume (0-1) */
    externalMixerVolume?: number;
    /** Whether a song is loaded on this deck */
    songLoaded?: boolean;
    /** Network device address */
    address?: string;
    /** Network device port */
    port?: number;
  }

  interface StateChangedData {
    /** Deck identifier formatted as "{player}{layer}" e.g. "1A", "2B" */
    deck?: string;
    /** Player number (1-4) */
    player?: number;
    /** Layer letter: "A", "B", "C", or "D" */
    layer?: string;
    /** Explicit play state */
    play?: boolean;
    /** Alternative play state */
    playState?: boolean;
    /** External mixer volume (0-1) */
    externalMixerVolume?: number;
    /** Master deck status */
    masterStatus?: boolean;
  }

  interface StageLinqOptions {
    maxRetries?: number;
    downloadDbSources?: boolean;
    /** Note: typo is in the stagelinq library API */
    enableFileTranfer?: boolean;
    logger?: StageLinqLogger;
  }

  /** Logger injected through options; StageLinq defaults to a silent logger. */
  interface StageLinqLogger {
    trace(message: string, ...args: unknown[]): void;
    debug(message: string, ...args: unknown[]): void;
    info(message: string, ...args: unknown[]): void;
    warn(message: string, ...args: unknown[]): void;
    error(message: string, ...args: unknown[]): void;
  }

  interface DevicesEmitter extends EventEmitter {
    on(event: "nowPlaying", listener: (status: NowPlayingStatus) => void): this;
    on(event: "stateChanged", listener: (status: StateChangedData) => void): this;
    on(event: "trackLoaded", listener: (status: NowPlayingStatus) => void): this;
    on(event: "connected", listener: (info: DeviceInfo) => void): this;
    on(event: "ready", listener: () => void): this;
    on(event: "disconnect", listener: () => void): this;
  }

  export const StageLinq: {
    options: StageLinqOptions;
    logger: StageLinqLogger;
    devices: DevicesEmitter;
    connect(): Promise<void>;
    disconnect(): Promise<void>;
  };
}
