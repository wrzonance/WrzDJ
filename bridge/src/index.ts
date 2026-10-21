/** CLI entrypoint: load configuration before constructing any session state. */
import { BridgeRuntime } from "./runtime/bridge-runtime.js";
import { startCli } from "./runtime/cli-lifecycle.js";
import { loadConfig } from "./runtime/config.js";
import { Logger } from "./shared/logger.js";
import { getPlugin, listPlugins } from "./plugins/plugin-registry.js";
import { registerBuiltinPlugins } from "./plugins/index.js";

const log = new Logger("Bridge");

async function main(): Promise<void> {
  registerBuiltinPlugins();
  const config = loadConfig();
  const plugin = getPlugin(config.plugin);
  if (!plugin) {
    throw new Error(`Unknown plugin "${config.plugin}". Available plugins: ${listPlugins().join(", ")}`);
  }
  const runtime = new BridgeRuntime(config, plugin);
  await startCli(runtime);
  log.info(`Bridge online for event ${config.eventCode} using ${config.plugin}`);
}

void main().catch((error: unknown) => {
  log.error(`Fatal error: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
