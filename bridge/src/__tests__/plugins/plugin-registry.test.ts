/**
 * Tests for plugin registry.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { EventEmitter } from "events";
import { PluginRegistry, type PluginMeta } from "../../plugins/plugin-registry.js";
import type { EquipmentSourcePlugin } from "../../plugins/plugin-types.js";

function mockMetadata(id = "mock"): PluginMeta {
  return {
    info: { id, name: "Mock Plugin", description: "Test plugin" },
    capabilities: {
      multiDeck: true, playState: true, faderLevel: false,
      masterDeck: false, albumMetadata: false,
    },
    configOptions: [
      { key: "port", label: "Port", type: "number", default: 9000, min: 1024, max: 65535 },
    ],
  };
}

function createMockPlugin(id = "mock"): EquipmentSourcePlugin {
  const emitter = new EventEmitter() as unknown as EquipmentSourcePlugin;
  Object.assign(emitter, mockMetadata(id), {
    isRunning: false,
    start: async () => {},
    stop: async () => {},
  });
  return emitter;
}

describe("Plugin Registry", () => {
  let registry: PluginRegistry;

  beforeEach(() => {
    registry = new PluginRegistry();
  });


  // Regression for constructor side effects during metadata lookup in 57cfcdc6867f.
  it("lists metadata without constructing plugins and isolates returned options", () => {
    const factory = vi.fn(() => createMockPlugin());
    const metadata = mockMetadata();
    registry.register(metadata, factory);
    const listed = registry.listMeta();
    expect(listed).toEqual([metadata]);
    expect(factory).not.toHaveBeenCalled();
    expect(listed[0].configOptions[0]).not.toBe(metadata.configOptions[0]);
    expect(registry.getMeta("mock")?.configOptions[0]).not.toBe(listed[0].configOptions[0]);
    registry.get("mock");
    expect(factory).toHaveBeenCalledOnce();
  });

  it("registers and retrieves a plugin", () => {
    registry.register(mockMetadata("mock"), () => createMockPlugin());
    const plugin = registry.get("mock");
    if (!plugin) throw new Error("Registered plugin was not returned");
    expect(plugin.info.id).toBe("mock");
  });

  it("returns null for unregistered plugin", () => {
    expect(registry.get("nonexistent")).toBeNull();
  });

  it("throws on duplicate registration", () => {
    registry.register(mockMetadata("mock"), () => createMockPlugin());
    expect(() => registry.register(mockMetadata("mock"), () => createMockPlugin())).toThrow(
      'Plugin "mock" is already registered'
    );
  });

  it("lists registered plugin IDs", () => {
    registry.register(mockMetadata("alpha"), () => createMockPlugin("alpha"));
    registry.register(mockMetadata("beta"), () => createMockPlugin("beta"));
    expect(registry.list()).toEqual(["alpha", "beta"]);
  });

  it("creates fresh instances on each getPlugin call", () => {
    registry.register(mockMetadata("mock"), () => createMockPlugin());
    const a = registry.get("mock");
    const b = registry.get("mock");
    expect(a).not.toBe(b);
  });

  it("isolates registrations between registry instances", () => {
    registry.register(mockMetadata("mock"), () => createMockPlugin());
    expect(new PluginRegistry().list()).toEqual([]);
  });

  it("returns plugin metadata via getPluginMeta", () => {
    registry.register(mockMetadata("mock"), () => createMockPlugin());
    const meta = registry.getMeta("mock");
    if (!meta) throw new Error("Registered plugin metadata was not returned");
    expect(meta.info.id).toBe("mock");
    expect(meta.capabilities.multiDeck).toBe(true);
    expect(meta.capabilities.faderLevel).toBe(false);
    expect(meta.configOptions).toHaveLength(1);
    expect(meta.configOptions[0].key).toBe("port");
    expect(meta.configOptions[0].default).toBe(9000);
  });

  it("returns null from getPluginMeta for unregistered plugin", () => {
    expect(registry.getMeta("nonexistent")).toBeNull();
  });

  it("lists metadata for all registered plugins", () => {
    registry.register(mockMetadata("alpha"), () => createMockPlugin("alpha"));
    registry.register(mockMetadata("beta"), () => createMockPlugin("beta"));
    const metas = registry.listMeta();
    expect(metas).toHaveLength(2);
    expect(metas[0].info.id).toBe("alpha");
    expect(metas[1].info.id).toBe("beta");
  });
});
