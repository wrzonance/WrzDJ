/**
 * Tests for the structured Logger.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  Logger,
  setLogHandler,
  setMinLogLevel,
  getMinLogLevel,
  getLogHandler,
  formatLogEntry,
  type LogEntry,
  type LogHandler,
} from "../../shared/logger.js";

describe("Logger", () => {
  let capturedEntries: LogEntry[];
  let handler: LogHandler;

  beforeEach(() => {
    capturedEntries = [];
    handler = (entry: LogEntry) => capturedEntries.push(entry);
    setLogHandler(handler);
    setMinLogLevel("debug");
  });

  afterEach(() => {
    setLogHandler(null);
    setMinLogLevel("info");
  });

  it("creates log entries with correct fields", () => {
    const log = new Logger("TestComponent");
    log.info("hello world");

    expect(capturedEntries).toHaveLength(1);
    const entry = capturedEntries[0]!;
    expect(entry.level).toBe("info");
    expect(entry.component).toBe("TestComponent");
    expect(entry.message).toBe("hello world");
    expect(entry.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });

  it("supports all log levels", () => {
    const log = new Logger("Test");
    log.debug("d");
    log.info("i");
    log.warn("w");
    log.error("e");

    expect(capturedEntries).toHaveLength(4);
    expect(capturedEntries.map((e) => e.level)).toEqual(["debug", "info", "warn", "error"]);
  });

  it("filters messages below minimum level", () => {
    setMinLogLevel("warn");
    const log = new Logger("Test");

    log.debug("should be dropped");
    log.info("should be dropped");
    log.warn("should pass");
    log.error("should pass");

    expect(capturedEntries).toHaveLength(2);
    expect(capturedEntries[0]!.level).toBe("warn");
    expect(capturedEntries[1]!.level).toBe("error");
  });

  it("getMinLogLevel returns current level", () => {
    setMinLogLevel("error");
    expect(getMinLogLevel()).toBe("error");
    setMinLogLevel("debug");
    expect(getMinLogLevel()).toBe("debug");
  });

  it("getLogHandler returns current handler", () => {
    expect(getLogHandler()).toBe(handler);
    setLogHandler(null);
    expect(getLogHandler()).toBeNull();
  });

  it("child logger prepends component prefix", () => {
    const parent = new Logger("Bridge");
    const child = parent.child("API");

    child.info("request sent");

    expect(capturedEntries).toHaveLength(1);
    expect(capturedEntries[0]!.component).toBe("Bridge:API");
  });

  it("child of child nests component prefixes", () => {
    const root = new Logger("Bridge");
    const child = root.child("Plugin").child("StageLinQ");

    child.warn("timeout");

    expect(capturedEntries).toHaveLength(1);
    expect(capturedEntries[0]!.component).toBe("Bridge:Plugin:StageLinQ");
  });

  describe("formatLogEntry", () => {
    it("formats entry as single-line string", () => {
      const entry: LogEntry = {
        timestamp: "2026-02-21T10:30:00.000Z",
        level: "info",
        component: "Bridge",
        message: "Starting...",
      };

      expect(formatLogEntry(entry)).toBe(
        "2026-02-21T10:30:00.000Z [INFO] [Bridge] Starting..."
      );
    });

    it("uppercases all level names", () => {
      const levels = ["debug", "info", "warn", "error"] as const;
      for (const level of levels) {
        const entry: LogEntry = {
          timestamp: "2026-01-01T00:00:00.000Z",
          level,
          component: "X",
          message: "m",
        };
        expect(formatLogEntry(entry)).toContain(`[${level.toUpperCase()}]`);
      }
    });
  });

  describe("default console output (no handler)", () => {
    beforeEach(() => {
      setLogHandler(null);
    });

    it("writes info to console.log", () => {
      const spy = vi.spyOn(console, "log").mockImplementation(() => {});
      const log = new Logger("Test");
      log.info("hello");

      expect(spy).toHaveBeenCalledOnce();
      expect(spy.mock.calls[0]![0]).toContain("[INFO] [Test] hello");
      spy.mockRestore();
    });

    it("writes warn to console.warn", () => {
      const spy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const log = new Logger("Test");
      log.warn("careful");

      expect(spy).toHaveBeenCalledOnce();
      expect(spy.mock.calls[0]![0]).toContain("[WARN] [Test] careful");
      spy.mockRestore();
    });

    it("writes error to console.error", () => {
      const spy = vi.spyOn(console, "error").mockImplementation(() => {});
      const log = new Logger("Test");
      log.error("failed");

      expect(spy).toHaveBeenCalledOnce();
      expect(spy.mock.calls[0]![0]).toContain("[ERROR] [Test] failed");
      spy.mockRestore();
    });

    it("writes debug to console.log", () => {
      const spy = vi.spyOn(console, "log").mockImplementation(() => {});
      setMinLogLevel("debug");
      const log = new Logger("Test");
      log.debug("trace");

      expect(spy).toHaveBeenCalledOnce();
      expect(spy.mock.calls[0]![0]).toContain("[DEBUG] [Test] trace");
      spy.mockRestore();
    });
  });

  it("handles setLogHandler(null) reset correctly", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    setLogHandler(null);

    const log = new Logger("Test");
    log.info("via console");

    expect(spy).toHaveBeenCalledOnce();
    expect(capturedEntries).toHaveLength(0); // Handler was removed
    spy.mockRestore();
  });
});
