import { spawnSync } from "node:child_process";
import { describe, expect, it, vi } from "vitest";

describe("CLI entrypoint", () => {
  it("registers each built-in plugin exactly once", async () => {
    vi.resetModules();
    const registry = await import("../../plugins/plugin-registry.js");
    const plugins = await import("../../plugins/index.js");
    plugins.registerBuiltinPlugins();
    plugins.registerBuiltinPlugins();

    expect(registry.listPlugins()).toEqual([
      "pioneer-prolink",
      "serato",
      "stagelinq",
      "traktor-broadcast",
    ]);
  });

  it("reports unknown plugins after loading the built-in plugin registry", () => {
    const result = spawnSync(process.execPath, ["--import", "tsx", "src/index.ts"], {
      encoding: "utf8",
      env: {
        ...process.env,
        WRZDJ_BRIDGE_API_KEY: "test-key",
        WRZDJ_EVENT_CODE: "TEST",
        WRZDJ_PLUGIN: "missing-plugin",
      },
    });
    const output = `${result.stdout}${result.stderr}`;

    expect(result.status).toBe(1);
    expect(output).toContain('Unknown plugin "missing-plugin"');
    expect(output).toContain("Available plugins:");
    expect(output).toContain("stagelinq");
  });
});
