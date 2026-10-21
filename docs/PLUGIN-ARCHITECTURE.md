# Bridge Plugin Architecture

The WrzDJ Bridge uses a plugin system to abstract DJ equipment detection. Each DJ software integration is a self-contained plugin that emits normalized events, allowing the bridge to support multiple DJ platforms without modifying its core logic.

## Architecture Overview

```
DJ Software  ──►  Plugin  ──►  PluginBridge  ──►  DeckStateManager  ──►  Backend API
                                (synthesis)         (state machine)        (now-playing)
```

| Layer | File | Responsibility |
|-------|------|----------------|
| Plugin | `bridge/src/plugins/*.ts` | Connects to DJ software, emits raw events |
| PluginBridge | `bridge/src/plugins/plugin-bridge.ts` | Normalizes events, synthesizes missing data |
| DeckStateManager | `bridge/src/deck/deck-state-manager.ts` | Per-deck state machine, debounce, live detection |
| Runtime | `bridge/src/runtime/bridge-runtime.ts` | Coordinates plugin, deck state, and backend delivery |
| Bridge entry | `bridge/src/index.ts` | Registers plugins, loads configuration, and starts the CLI runtime |

## Core Interfaces

Plugin contracts are defined in `bridge/src/plugins/plugin-types.ts`; shared track values live in
`bridge/src/shared/track-types.ts`.

### EquipmentSourcePlugin

Every plugin implements this interface, which narrows Node.js event methods to `PluginEventMap`:

```typescript
interface EquipmentSourcePlugin extends TypedEventEmitter<PluginEventMap> {
  readonly info: PluginInfo;
  readonly capabilities: PluginCapabilities;
  readonly configOptions: readonly PluginConfigOption[];
  readonly isRunning: boolean;

  start(config?: Record<string, unknown>): Promise<void>;
  stop(): Promise<void>;
}
```

- `configOptions` declares user-configurable settings for this plugin (see PluginConfigOption below).
- `start()` initializes the connection to the DJ software. The optional `config` parameter carries plugin-specific settings (e.g., port number for Traktor).
- `stop()` tears down the connection and cleans up all resources.
- Both methods are async and must be safe to call in sequence.

### PluginInfo

Static metadata used for display and registry lookup:

```typescript
interface PluginInfo {
  readonly id: string;          // Registry key, e.g. "stagelinq"
  readonly name: string;        // Human-readable, e.g. "Denon StageLinQ"
  readonly description: string;
}
```

### PluginCapabilities

Declares what data the plugin can provide. PluginBridge uses these flags to decide what to synthesize:

```typescript
interface PluginCapabilities {
  readonly multiDeck: boolean;      // Reports per-deck data (vs single stream)
  readonly playState: boolean;      // Provides explicit play/pause events
  readonly faderLevel: boolean;     // Provides channel fader levels
  readonly masterDeck: boolean;     // Provides master deck assignment
  readonly albumMetadata: boolean;  // Provides album info with tracks
}
```

### PluginConfigOption

Declares a user-configurable setting for a plugin. The bridge-app UI renders these dynamically — no hardcoded UI is needed per plugin.

```typescript
interface PluginConfigOption {
  readonly key: string;           // Setting key, e.g. "port"
  readonly label: string;         // Human-readable label, e.g. "Broadcast port"
  readonly type: "number" | "string" | "boolean";
  readonly default: number | string | boolean;
  readonly description?: string;  // Tooltip/help text
  readonly min?: number;          // For type: "number" only
  readonly max?: number;          // For type: "number" only
}
```

Plugins with no user-configurable options set `configOptions: []`.

**How capabilities drive synthesis:**

| Capability | When `false` | PluginBridge behavior |
|------------|-------------|----------------------|
| `multiDeck` | Single combined stream | All deck IDs mapped to virtual deck `"1"` |
| `playState` | No play/pause signals | Automatically sets play state to `true` when track metadata arrives |
| `faderLevel` | No fader data | Fader detection settings ignored |
| `masterDeck` | No master deck info | Master deck priority settings ignored |
| `albumMetadata` | No album field | Album field omitted from track reports |

## Plugin Events

Plugins emit these events via `EventEmitter`. PluginBridge subscribes to all of them.

| Event | Payload | Description |
|-------|---------|-------------|
| `track` | `{ deckId, track: { title, artist, album? } \| null }` | Track loaded/changed on a deck, or `null` for unload |
| `playState` | `{ deckId, isPlaying }` | Deck play/pause state changed |
| `fader` | `{ deckId, level }` | Channel fader level changed (0.0 to 1.0) |
| `masterDeck` | `{ deckId }` | Deck became the master |
| `connection` | `{ connected, deviceName? }` | Device connected or disconnected |
| `ready` | (none) | Plugin fully initialized and ready |
| `log` | `string` | Diagnostic message |
| `error` | `Error` | Error condition |

## Plugin Registry

The registry (`bridge/src/plugins/plugin-registry.ts`) stores static metadata with each factory, keyed by `metadata.info.id`. Metadata lookup returns independent copies without constructing plugins. Each call to `getPlugin()` creates a fresh instance.

```typescript
import {
  registerPlugin, getPlugin, listPlugins,
  getPluginMeta, listPluginMeta,
} from "./plugin-registry.js";

// Register static metadata and a factory at application startup
registerPlugin(MyPlugin.metadata, () => new MyPlugin());

// Create an instance
const plugin = getPlugin("my-plugin"); // Returns new MyPlugin() or null

// List registered IDs
const ids = listPlugins(); // ["pioneer-prolink", "stagelinq", "traktor-broadcast", "my-plugin"]

// Get serializable metadata (info + capabilities + configOptions)
const meta = getPluginMeta("my-plugin"); // PluginMeta | null
const allMeta = listPluginMeta();        // PluginMeta[]
```

`getPluginMeta()` and `listPluginMeta()` return plain objects safe for IPC transfer. The bridge-app uses `listPluginMeta()` to populate the protocol dropdown and render plugin-specific config inputs dynamically.

Built-in plugins register themselves in `bridge/src/plugins/index.ts`, which is imported as a side-effect at startup.

## Built-in Plugins

### Denon StageLinQ (`stagelinq`)

**File:** `bridge/src/plugins/stagelinq-plugin.ts`

Connects to Denon DJ equipment (SC6000, SC Live, etc.) over the local network using the StageLinQ protocol. Full capabilities — reports per-deck metadata, play state, fader levels, master deck, and album info.

| Capability | Value |
|------------|-------|
| `multiDeck` | `true` |
| `playState` | `true` |
| `faderLevel` | `true` |
| `masterDeck` | `true` |
| `albumMetadata` | `true` |

**Configuration:** No user-configurable options (`configOptions: []`). The plugin discovers devices via StageLinQ network announcements.

### Serato DJ (`serato`)

**File:** `bridge/src/plugins/serato-plugin.ts`

Watches Serato DJ's binary session files for track metadata. When Serato loads a track to a deck, it appends an OENT/ADAT chunk to the active session file in `Music/_Serato_/History/Sessions/`. The plugin polls the file for growth and parses new binary data to extract track info.

| Capability | Value |
|------------|-------|
| `multiDeck` | `true` |
| `playState` | `false` |
| `faderLevel` | `false` |
| `masterDeck` | `false` |
| `albumMetadata` | `true` |

**Configuration:**

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `seratoPath` | `string` | (auto-detect) | Path to Serato sessions folder |
| `pollInterval` | `number` | `1000` | How often to check for new track data (ms) |

**How it works:**

1. On start, locates the most recent `.session` file in the sessions directory
2. Polls the file for new bytes at the configured interval
3. Parses new OENT/ADAT chunks and emits `track` events per deck
4. Watches the directory for new session files (Serato creates a new one each session)
5. Deduplicates identical consecutive tracks per deck

**Limitations:**

- Cannot detect play/pause state — only "track loaded to deck"
- PluginBridge synthesizes play state from metadata changes
- No fader or master deck information available

**No npm dependencies** — uses only Node.js built-ins for file I/O and binary parsing.

### Traktor Broadcast (`traktor-broadcast`)

**File:** `bridge/src/plugins/traktor-broadcast-plugin.ts`

Receives track metadata from Traktor via its built-in broadcast feature. Traktor sends an Icecast-compatible stream to a local HTTP server, and the plugin extracts ICY metadata (`StreamTitle='Artist - Title'`) from the interleaved audio/metadata stream.

| Capability | Value |
|------------|-------|
| `multiDeck` | `false` |
| `playState` | `false` |
| `faderLevel` | `false` |
| `masterDeck` | `false` |
| `albumMetadata` | `false` |

**Configuration:**

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `port` | `number` | `8123` | Local port for the Icecast server |

**Traktor setup:** Settings > Broadcasting > Address: `127.0.0.1`, Port: `8123` (or your configured port).

Because all capabilities are `false`, PluginBridge synthesizes everything: deck IDs are normalized to `"1"`, and play state is set to `true` whenever track metadata arrives.

### Pioneer PRO DJ LINK (`pioneer-prolink`)

**File:** `bridge/src/plugins/pioneer-prolink-plugin.ts`

Connects to Pioneer DJ equipment (CDJ-3000, CDJ-2000NXS2, etc.) via the PRO DJ LINK protocol using the [`alphatheta-connect`](https://github.com/chrisle/alphatheta-connect) npm library (maintained fork of `prolink-connect` with encrypted Rekordbox DB support). Joins the network as a virtual CDJ device, monitors CDJ status packets, and queries track metadata from CDJ databases.

| Capability | Value |
|------------|-------|
| `multiDeck` | `true` |
| `playState` | `true` |
| `faderLevel` | `true` |
| `masterDeck` | `true` |
| `albumMetadata` | `true` |

**Configuration:** No user-configurable options (`configOptions: []`). The plugin uses `autoconfigFromPeers()` for automatic network discovery.

**How it works:**

1. `bringOnline()` opens UDP sockets and listens for device announcements
2. `autoconfigFromPeers()` waits for the first CDJ to appear and configures the network interface
3. `connect()` announces the plugin as a virtual CDJ (device ID 5) and activates services
4. CDJ status packets arrive via `statusEmitter.on("status")` — the plugin maps:
   - `PlayState.Playing` → `playState` event
   - `isOnAir` → binary fader level (1.0 / 0.0)
   - `isMaster` → `masterDeck` event
   - Track ID changes → metadata query via `network.db.getMetadata()` → `track` event

**Important caveats:**

- Cannot coexist with Rekordbox on the same machine (both use the same protocol slots)
- Requires Ethernet connection — CDJs must be on the same LAN (not USB-only)
- On-air detection requires a compatible DJM mixer connected via Ethernet; without one, `isOnAir` defaults to `true` (fader detection becomes a no-op)
- Occupies one virtual CDJ slot (max 5 real CDJs when plugin is running)

## Creating a New Plugin

### 1. Create the plugin file

Create `bridge/src/plugins/my-plugin.ts`:

```typescript
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";
import type { PluginMeta } from "./plugin-registry.js";
import type {
  EquipmentSourcePlugin,
  PluginEventArguments,
} from "./plugin-types.js";

export class MyPlugin extends TypedEventEmitter<PluginEventArguments> implements EquipmentSourcePlugin {
  static readonly metadata: PluginMeta = {
    info: {
      id: "my-plugin",
      name: "My DJ Software",
      description: "Connects to My DJ Software via ...",
    },
    capabilities: {
      multiDeck: true,
      playState: true,
      faderLevel: false,
      masterDeck: false,
      albumMetadata: false,
    },
    configOptions: [],
  };

  readonly info = structuredClone(MyPlugin.metadata.info);
  readonly capabilities = structuredClone(MyPlugin.metadata.capabilities);
  readonly configOptions = structuredClone(MyPlugin.metadata.configOptions);

  private running = false;

  get isRunning(): boolean {
    return this.running;
  }

  async start(config?: Record<string, unknown>): Promise<void> {
    if (this.running) {
      throw new Error("My plugin is already running");
    }
    this.running = true;

    // Initialize your connection here
    // When you detect a track change:
    //   this.emit("track", { deckId: "1", track: { title, artist } });
    // When you detect play state:
    //   this.emit("playState", { deckId: "1", isPlaying: true });
  }

  async stop(): Promise<void> {
    if (!this.running) return;
    this.running = false;

    // Tear down connections, close sockets/servers
    this.removeAllListeners();
  }
}
```

### 2. Register the plugin

Add to `bridge/src/plugins/index.ts`:

```typescript
import { MyPlugin } from "./my-plugin.js";

registerPlugin(MyPlugin.metadata, () => new MyPlugin());
```

### 3. Write tests

Create `bridge/src/__tests__/my-plugin.test.ts`. Follow the patterns in the existing test files:

- Test plugin metadata and capabilities
- Test `start()`/`stop()` lifecycle (idempotency, error on double-start)
- Test event emission for track changes
- Test deduplication if applicable
- Use `port: 0` for OS-assigned ports if your plugin runs a server, and `AbortController` for streaming connections

Run with:

```bash
cd bridge && npm run test:run
```

## UI Integration

The bridge-app Settings panel is fully data-driven from plugin metadata. No hardcoded plugin knowledge exists in the UI.

**How it works:**

1. On mount, the renderer calls `api.listPluginMeta()` via IPC
2. The main process calls `listPluginMeta()` from the plugin registry, which creates temporary plugin instances, reads their metadata, and returns serializable `PluginMeta` objects
3. The protocol dropdown is populated from `PluginMeta[].info`
4. When a protocol is selected, `PluginConfigInput` components are rendered for each `configOption` based on its `type` (number, string, boolean)
5. Capability-based toggles (fader detection, master deck priority) are conditionally shown based on `PluginMeta.capabilities`

Adding a new plugin with `configOptions` automatically surfaces those options in the UI with no frontend changes needed.

## Design Principles

**Capability-driven synthesis.** Plugins declare what they can provide. PluginBridge fills in the gaps automatically. A plugin that only provides track metadata still works — PluginBridge synthesizes play state and normalizes deck IDs.

**No shared state.** Each plugin instance is independent. The registry creates fresh instances on every `getPlugin()` call. Plugins communicate only through events.

**Minimal dependencies.** The Traktor plugin uses only Node.js built-in `http` module — no additional npm packages. Prefer built-in modules when possible.

**Protocol-agnostic state machine.** DeckStateManager knows nothing about StageLinQ, Icecast, or any DJ software. It only understands deck state transitions and timing thresholds. This separation means new plugins never need to modify the state machine.

## File Map

```
bridge/src/
  index.ts                    # CLI composition entry
  electron-api.ts             # Stable package entry consumed by bridge-app
  deck/                       # Deck state machine and deck event types
  runtime/                    # BridgeRuntime, CLI lifecycle, configuration
  transport/                  # Backend clients, retries, command polling, delivery history
  shared/                     # TrackInfo, typed emitter, logging, time units
  plugins/
    index.ts                   # Explicit registerBuiltinPlugins composition function
    plugin-types.ts            # EquipmentSourcePlugin, events, capabilities
    plugin-registry.ts         # Factory registry: register/get/list plugins
    plugin-bridge.ts           # Translation layer: plugin events → DeckStateManager
    pioneer-prolink-plugin.ts  # Pioneer PRO DJ LINK integration
    serato-plugin.ts           # Serato DJ session file watcher
    serato-session-parser.ts   # Binary parser for Serato session files
    stagelinq-plugin.ts        # Denon StageLinQ integration
    traktor-broadcast-plugin.ts # Traktor Broadcast/Icecast integration
  __tests__/
    plugins/                   # Adapter lifecycle, parsing, synthesis, and registry tests
    deck/                      # Deck state machine tests
    transport/                 # Backend delivery and retry tests
    runtime/                   # Runtime composition and CLI subprocess tests
    shared/                    # Shared event and time contracts
    local-library/             # Local library tests
    contracts/                 # Cross-provider compatibility tests
    fixtures/                  # Shared test data and subprocess entrypoints

bridge-app/src/
  shared/types.ts              # PluginMeta, PluginConfigOption, BridgeSettings.protocol
  main/ipc-handlers.ts         # IPC handler: exposes listPluginMeta to renderer
  main/bridge-runner.ts        # Electron adapter: maps BridgeRuntime status and events to app contracts
  preload/preload.ts           # contextBridge: exposes listPluginMeta to renderer
  renderer/api.ts              # Typed API wrapper for renderer
  renderer/components/
    SettingsPanel.tsx           # Data-driven protocol selector and config UI
```
