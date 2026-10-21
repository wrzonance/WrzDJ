import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("bridge configuration", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("WRZDJ_BRIDGE_API_KEY", "test-key");
    vi.stubEnv("WRZDJ_EVENT_CODE", "TEST123");
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  // Regression: 57cfcdc6867f accepted malformed URLs until the first request.
  it.each(["not-a-url", "/relative", "ftp://example.com", "data:text/plain,hello"])(
    "rejects an unusable API URL: %s",
    async (apiUrl) => {
      vi.stubEnv("WRZDJ_API_URL", apiUrl);
      const { loadConfig } = await import("../../runtime/config.js");
      expect(() => loadConfig()).toThrow(/WRZDJ_API_URL.*HTTP/);
    },
  );

  it.each(["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000", "https://example.com"])(
    "accepts %s without warning",
    async (apiUrl) => {
      vi.stubEnv("WRZDJ_API_URL", apiUrl);
      const { loadConfig } = await import("../../runtime/config.js");
      expect(() => loadConfig()).not.toThrow();
      expect(console.warn).not.toHaveBeenCalled();
    },
  );

  it("warns about cleartext credentials sent to a remote server", async () => {
    vi.stubEnv("WRZDJ_API_URL", "http://example.com");
    const { loadConfig } = await import("../../runtime/config.js");
    loadConfig();
    expect(console.warn).toHaveBeenCalledWith(expect.stringContaining("Using HTTP with a remote server"));
  });

  it("maps only deck-state settings to the adapter configuration", async () => {
    vi.stubEnv("WRZDJ_API_URL", "https://api.example.com");
    const { loadConfig, toDeckStateManagerConfig } = await import("../../runtime/config.js");
    const config = loadConfig();

    expect(toDeckStateManagerConfig(config)).toEqual({
      liveThresholdSeconds: config.liveThresholdSeconds,
      pauseGraceSeconds: config.pauseGraceSeconds,
      nowPlayingPauseSeconds: config.nowPlayingPauseSeconds,
      useFaderDetection: config.useFaderDetection,
      masterDeckPriority: config.masterDeckPriority,
    });
  });
});
