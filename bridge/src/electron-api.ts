/** Supported bridge surface for Electron consumers. */
export {
  BridgeRuntime,
  type BridgeRuntimeEventMap,
  type BridgeRuntimeSnapshot,
} from "./runtime/bridge-runtime.js";
export { loadConfig, type BridgeConfig } from "./runtime/config.js";
export { Logger, type LogLevel } from "./shared/logger.js";
export { getPlugin, listPluginMeta, listPlugins, type PluginMeta } from "./plugins/plugin-registry.js";
export { registerBuiltinPlugins } from "./plugins/index.js";
export type { CircuitState } from "./transport/circuit-breaker.js";
export type { DeckState, DeckStateSnapshot, DeckStateType, DeckStatusSnapshot } from "./deck/deck-state.js";
export type { EquipmentSourcePlugin, PluginCapabilities, PluginConfigOption } from "./plugins/plugin-types.js";
