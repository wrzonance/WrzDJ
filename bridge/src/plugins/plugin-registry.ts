/**
 * Plugin registry for WrzDJ Bridge.
 *
 * Stores static metadata alongside factories keyed by plugin ID.
 * Applications register plugins explicitly; only getPlugin() constructs them.
 */
import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConfigOption,
  PluginInfo,
} from "./plugin-types.js";

export type PluginFactory = () => EquipmentSourcePlugin;

/** Serializable plugin metadata (no EventEmitter, safe for IPC). */
export interface PluginMeta {
  readonly info: PluginInfo;
  readonly capabilities: PluginCapabilities;
  readonly configOptions: readonly PluginConfigOption[];
}

export class PluginRegistry {
  private readonly registrations = new Map<string, { factory: PluginFactory; metadata: PluginMeta }>();

  register(metadata: PluginMeta, factory: PluginFactory): void {
    const id = metadata.info.id;
    if (this.registrations.has(id)) {
      throw new Error(`Plugin "${id}" is already registered`);
    }
    this.registrations.set(id, { factory, metadata: structuredClone(metadata) });
  }

  get(id: string): EquipmentSourcePlugin | null {
    const registration = this.registrations.get(id);
    return registration ? registration.factory() : null;
  }

  getMeta(id: string): PluginMeta | null {
    const registration = this.registrations.get(id);
    return registration ? structuredClone(registration.metadata) : null;
  }

  listMeta(): PluginMeta[] {
    return [...this.registrations.values()].map(({ metadata }) => structuredClone(metadata));
  }

  list(): string[] {
    return [...this.registrations.keys()];
  }
}

const registry = new PluginRegistry();

/** Register static metadata and a factory. Throws if the metadata ID is registered. */
export function registerPlugin(metadata: PluginMeta, factory: PluginFactory): void {
  registry.register(metadata, factory);
}

/** Create a plugin instance by ID. Returns null if not found. */
export function getPlugin(id: string): EquipmentSourcePlugin | null {
  return registry.get(id);
}

/** Get serializable metadata for a plugin by ID. Returns null if not found. */
export function getPluginMeta(id: string): PluginMeta | null {
  return registry.getMeta(id);
}

/** Get serializable metadata for all registered plugins. */
export function listPluginMeta(): PluginMeta[] {
  return registry.listMeta();
}

/** List all registered plugin IDs. */
export function listPlugins(): string[] {
  return registry.list();
}
