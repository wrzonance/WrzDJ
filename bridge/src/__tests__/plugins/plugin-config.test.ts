import { describe, expect, it } from "vitest";
import { SeratoPlugin } from "../../plugins/serato-plugin.js";
import { TraktorBroadcastPlugin } from "../../plugins/traktor-broadcast-plugin.js";

describe("plugin configuration boundaries", () => {
  // Regression: 57cfcdc6867f asserted unknown config values as strings/numbers.
  it.each([false, 0, [], {}, null, "bad\0path"])("rejects invalid Serato paths: %j", async (seratoPath) => {
    const plugin = new SeratoPlugin();
    try {
      await expect(plugin.start({ seratoPath })).rejects.toThrow("Invalid seratoPath");
      expect(plugin.isRunning).toBe(false);
    } finally {
      await plugin.stop();
    }
  });

  it.each(["1000", null, NaN, Infinity, 199, 10001])("rejects invalid Serato polling interval: %j", async (pollInterval) => {
    const plugin = new SeratoPlugin();
    try {
      await expect(plugin.start({ pollInterval })).rejects.toThrow("Invalid pollInterval");
      expect(plugin.isRunning).toBe(false);
    } finally {
      await plugin.stop();
    }
  });

  it.each(["8000", null, NaN, Infinity, -1, 65536])("rejects invalid Traktor port: %j", async (port) => {
    const plugin = new TraktorBroadcastPlugin();
    try {
      await expect(plugin.start({ port })).rejects.toThrow("Invalid port");
      expect(plugin.isRunning).toBe(false);
    } finally {
      await plugin.stop();
    }
  });
});
