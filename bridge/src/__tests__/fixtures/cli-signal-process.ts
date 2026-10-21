import { EventEmitter } from "node:events";
import { BridgeRuntime } from "../../runtime/bridge-runtime.js";
import { startCli } from "../../runtime/cli-lifecycle.js";
import { loadConfig } from "../../runtime/config.js";
import type { EquipmentSourcePlugin } from "../../plugins/plugin-types.js";

const plugin = new EventEmitter() as unknown as EquipmentSourcePlugin;
Object.assign(plugin, {
  info: { id: "test", name: "Test", description: "Controlled CLI test plugin" },
  capabilities: {
    multiDeck: true,
    playState: true,
    faderLevel: true,
    masterDeck: true,
    albumMetadata: true,
  },
  configOptions: [],
  start: async () => {},
  stop: async () => { process.stdout.write("PLUGIN_STOPPED\n"); },
});

process.on("beforeExit", () => {
  process.stdout.write(`SIGTERM_HANDLERS=${process.listenerCount("SIGTERM")}\n`);
});

await startCli(new BridgeRuntime(loadConfig(), plugin));
process.stdout.write("READY\n");
