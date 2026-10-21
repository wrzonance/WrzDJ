import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { startCli, type CliSignalProcess } from "../../runtime/cli-lifecycle.js";

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

class TestSignalProcess extends EventEmitter implements CliSignalProcess {
  exitCode: number | undefined;
}

describe("CLI signal lifecycle", () => {
  it("handles termination while runtime startup is still pending", async () => {
    const signals = new TestSignalProcess();
    const startup = deferred<void>();
    const shutdown = deferred<void>();
    const runtime = {
      start: vi.fn(() => startup.promise),
      stop: vi.fn(() => shutdown.promise),
    };

    // Regression for 57cfcdc6867f: signals during plugin startup were unhandled.
    const started = startCli(runtime, signals);
    expect(signals.listenerCount("SIGINT")).toBe(1);
    expect(signals.listenerCount("SIGTERM")).toBe(1);

    signals.emit("SIGTERM");
    expect(runtime.stop).toHaveBeenCalledOnce();
    expect(signals.listenerCount("SIGTERM")).toBe(1);

    shutdown.resolve();
    await vi.waitFor(() => {
      expect(signals.listenerCount("SIGINT")).toBe(0);
      expect(signals.listenerCount("SIGTERM")).toBe(0);
    });
    startup.resolve();
    await started;
    expect(signals.exitCode).toBe(0);
  });

  it("removes signal handlers when startup rejects", async () => {
    const signals = new TestSignalProcess();
    const runtime = {
      start: vi.fn().mockRejectedValue(new Error("plugin startup failed")),
      stop: vi.fn().mockResolvedValue(undefined),
    };

    await expect(startCli(runtime, signals)).rejects.toThrow("plugin startup failed");
    expect(signals.listenerCount("SIGINT")).toBe(0);
    expect(signals.listenerCount("SIGTERM")).toBe(0);
  });
});
