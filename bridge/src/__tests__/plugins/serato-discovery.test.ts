import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readdirSync, statSync, watch, type Stats } from "fs";
import { findLatestSessionFile } from "../../plugins/serato-session-parser.js";
import { SeratoPlugin } from "../../plugins/serato-plugin.js";

vi.mock("fs", async (importOriginal) => ({
  ...await importOriginal<typeof import("fs")>(),
  readdirSync: vi.fn(),
  statSync: vi.fn(),
  watch: vi.fn(() => ({ close: vi.fn() })),
}));

const denied = Object.assign(new Error("permission denied"), { code: "EACCES" });
const missing = Object.assign(new Error("missing"), { code: "ENOENT" });

describe("Serato discovery errors", () => {
  let plugin: SeratoPlugin;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(readdirSync).mockReturnValue([]);
    vi.mocked(statSync).mockReset();
    plugin = new SeratoPlugin();
  });

  afterEach(async () => {
    await plugin.stop();
    vi.useRealTimers();
  });

  // Regression: 57cfcdc6867f swallowed all directory/stat failures.
  it("preserves the filesystem error when the directory is inaccessible", () => {
    vi.mocked(readdirSync).mockImplementation(() => { throw denied; });
    expect(() => findLatestSessionFile("/sessions")).toThrow(denied);
  });

  it("returns null for a missing directory", () => {
    vi.mocked(readdirSync).mockImplementation(() => { throw missing; });
    expect(findLatestSessionFile("/sessions")).toBeNull();
  });

  it("preserves unexpected stat errors", () => {
    vi.mocked(readdirSync).mockReturnValue(["live.session"] as never);
    vi.mocked(statSync).mockImplementation(() => { throw denied; });
    expect(() => findLatestSessionFile("/sessions")).toThrow(denied);
  });

  it("tolerates a file disappearing between listing and stat", () => {
    vi.mocked(readdirSync).mockReturnValue(["live.session"] as never);
    vi.mocked(statSync).mockImplementation(() => { throw missing; });
    expect(findLatestSessionFile("/sessions")).toBeNull();
  });

  it("ignores directories ending in .session", () => {
    vi.mocked(readdirSync).mockReturnValue(["folder.session"] as never);
    vi.mocked(statSync).mockReturnValue({ mtimeMs: 100, isFile: () => false } as Stats);
    expect(findLatestSessionFile("/sessions")).toBeNull();
  });

  it("does not claim to be running after discovery fails at startup", async () => {
    vi.mocked(readdirSync).mockImplementation(() => { throw denied; });
    await expect(plugin.start({ seratoPath: "/sessions" })).rejects.toThrow(denied);
    expect(plugin.isRunning).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reports discovery failures during polling without throwing from the timer", async () => {
    const log = vi.fn();
    plugin.on("log", log);
    await plugin.start({ seratoPath: "/sessions", pollInterval: 200 });
    vi.mocked(readdirSync).mockImplementation(() => { throw denied; });
    expect(() => vi.advanceTimersByTime(200)).not.toThrow();
    expect(log).toHaveBeenCalledWith(expect.stringContaining("permission denied"));
  });

  it("reports discovery failures from directory notifications", async () => {
    const log = vi.fn();
    plugin.on("log", log);
    await plugin.start({ seratoPath: "/sessions" });
    vi.mocked(readdirSync).mockImplementation(() => { throw denied; });
    const listener = vi.mocked(watch).mock.calls[0]![1] as (event: string, file: string) => void;
    expect(() => listener("rename", "live.session")).not.toThrow();
    expect(log).toHaveBeenCalledWith(expect.stringContaining("permission denied"));
  });
});
