/**
 * Built-in plugin registration.
 *
 * Call registerBuiltinPlugins at an application composition boundary.
 */
import { registerPlugin } from "./plugin-registry.js";
import { PioneerProlinkPlugin } from "./pioneer-prolink-plugin.js";
import { SeratoPlugin } from "./serato-plugin.js";
import { StageLinqPlugin } from "./stagelinq-plugin.js";
import { TraktorBroadcastPlugin } from "./traktor-broadcast-plugin.js";

let registered = false;

/** Register the bundled integrations once at an application composition boundary. */
export function registerBuiltinPlugins(): void {
  if (registered) return;
  registerPlugin(PioneerProlinkPlugin.metadata, () => new PioneerProlinkPlugin());
  registerPlugin(SeratoPlugin.metadata, () => new SeratoPlugin());
  registerPlugin(StageLinqPlugin.metadata, () => new StageLinqPlugin());
  registerPlugin(TraktorBroadcastPlugin.metadata, () => new TraktorBroadcastPlugin());
  registered = true;
}
