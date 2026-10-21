/**
 * Tests for CircuitBreaker — protects the bridge from hammering an unreachable backend.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { CircuitBreaker } from "../../transport/circuit-breaker.js";

function recordFailure(cb: CircuitBreaker): void {
  const admission = cb.beginRequest();
  if (!admission) throw new Error("Expected request admission");
  cb.recordFailure(admission);
}

function recordSuccess(cb: CircuitBreaker): void {
  const admission = cb.beginRequest();
  if (!admission) throw new Error("Expected request admission");
  cb.recordSuccess(admission);
}

describe("CircuitBreaker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts in CLOSED state", () => {
    const cb = new CircuitBreaker();
    expect(cb.getState()).toBe("CLOSED");
    expect(cb.getConsecutiveFailures()).toBe(0);
  });

  it("allows requests in CLOSED state", () => {
    const cb = new CircuitBreaker();
    expect(cb.beginRequest()).not.toBeNull();
  });

  it("stays CLOSED on fewer failures than threshold", () => {
    const cb = new CircuitBreaker({ failureThreshold: 3 });
    recordFailure(cb);
    recordFailure(cb);
    expect(cb.getState()).toBe("CLOSED");
    expect(cb.getConsecutiveFailures()).toBe(2);
    expect(cb.beginRequest()).not.toBeNull();
  });

  it("transitions to OPEN after reaching failure threshold", () => {
    const cb = new CircuitBreaker({ failureThreshold: 3 });
    const stateChanges: Array<{ from: string; to: string }> = [];
    cb.on("stateChange", (change: { from: string; to: string }) => stateChanges.push(change));

    recordFailure(cb);
    recordFailure(cb);
    recordFailure(cb);

    expect(cb.getState()).toBe("OPEN");
    expect(stateChanges).toHaveLength(1);
    expect(stateChanges[0]).toEqual({ from: "CLOSED", to: "OPEN" });
  });

  it("blocks requests in OPEN state before cooldown", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 60_000 });
    recordFailure(cb);
    expect(cb.getState()).toBe("OPEN");
    expect(cb.beginRequest()).toBeNull();
  });

  it("transitions to HALF_OPEN after cooldown", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 60_000 });
    recordFailure(cb);
    expect(cb.getState()).toBe("OPEN");

    vi.advanceTimersByTime(60_000);
    const probe = cb.beginRequest();
    expect(probe).not.toBeNull();
    expect(cb.getState()).toBe("HALF_OPEN");
  });

  it("transitions HALF_OPEN → CLOSED on success", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 1000 });
    const stateChanges: Array<{ from: string; to: string }> = [];
    cb.on("stateChange", (change: { from: string; to: string }) => stateChanges.push(change));

    recordFailure(cb); // → OPEN
    vi.advanceTimersByTime(1000);
    const probe = cb.beginRequest(); // → HALF_OPEN
    cb.recordSuccess(probe!); // → CLOSED

    expect(cb.getState()).toBe("CLOSED");
    expect(cb.getConsecutiveFailures()).toBe(0);
    expect(stateChanges).toEqual([
      { from: "CLOSED", to: "OPEN" },
      { from: "OPEN", to: "HALF_OPEN" },
      { from: "HALF_OPEN", to: "CLOSED" },
    ]);
  });

  it("ignores a late CLOSED request success while a HALF_OPEN probe is active", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 1000 });
    const lateRequest = cb.beginRequest();
    recordFailure(cb);
    vi.advanceTimersByTime(1000);
    const probe = cb.beginRequest();

    expect(lateRequest).not.toBeNull();
    expect(probe).not.toBeNull();
    cb.recordSuccess(lateRequest!);
    expect(cb.getState()).toBe("HALF_OPEN");

    cb.recordSuccess(probe!);
    expect(cb.getState()).toBe("CLOSED");
  });

  it("ignores an old CLOSED admission after a probe starts a new CLOSED generation", () => {
    const cb = new CircuitBreaker({ failureThreshold: 2, cooldownMs: 1000 });
    const oldRequest = cb.beginRequest();
    recordFailure(cb);
    recordFailure(cb);
    vi.advanceTimersByTime(1000);
    const probe = cb.beginRequest();
    cb.recordSuccess(probe!);

    const newRequest = cb.beginRequest();
    cb.recordFailure(newRequest!);
    cb.recordSuccess(oldRequest!);

    expect(cb.getState()).toBe("CLOSED");
    expect(cb.getConsecutiveFailures()).toBe(1);
  });

  it("transitions HALF_OPEN → OPEN on failure (resets cooldown)", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 1000 });
    recordFailure(cb); // → OPEN
    vi.advanceTimersByTime(1000);
    const probe = cb.beginRequest(); // → HALF_OPEN
    cb.recordFailure(probe!); // → OPEN

    expect(cb.getState()).toBe("OPEN");
    // Should need another full cooldown
    expect(cb.beginRequest()).toBeNull();
    vi.advanceTimersByTime(1000);
    expect(cb.beginRequest()).not.toBeNull();
    expect(cb.getState()).toBe("HALF_OPEN");
  });

  it("resets failure count on success in CLOSED state", () => {
    const cb = new CircuitBreaker({ failureThreshold: 3 });
    recordFailure(cb);
    recordFailure(cb);
    recordSuccess(cb);
    expect(cb.getConsecutiveFailures()).toBe(0);
    expect(cb.getState()).toBe("CLOSED");
  });

  it("reset() returns to initial state", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 1000 });
    recordFailure(cb); // → OPEN
    expect(cb.getState()).toBe("OPEN");

    cb.reset();
    expect(cb.getState()).toBe("CLOSED");
    expect(cb.getConsecutiveFailures()).toBe(0);
    expect(cb.beginRequest()).not.toBeNull();
  });

  it("uses default config values", () => {
    const cb = new CircuitBreaker();
    // Default threshold is 3
    recordFailure(cb);
    recordFailure(cb);
    expect(cb.getState()).toBe("CLOSED");
    recordFailure(cb);
    expect(cb.getState()).toBe("OPEN");

    // Default cooldown is 60s
    vi.advanceTimersByTime(59_999);
    expect(cb.beginRequest()).toBeNull();
    vi.advanceTimersByTime(1);
    const probe = cb.beginRequest();
    expect(probe).not.toBeNull();
    cb.recordSuccess(probe!);
  });

  it("blocks concurrent probes in HALF_OPEN state", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 1000 });
    recordFailure(cb); // → OPEN
    vi.advanceTimersByTime(1000);

    // First call transitions to HALF_OPEN and admits the probe
    const probe = cb.beginRequest();
    expect(probe).not.toBeNull();
    expect(cb.getState()).toBe("HALF_OPEN");

    // Second call while probe is in-flight should be blocked
    expect(cb.beginRequest()).toBeNull();

    // After recording result, probes should be allowed again
    cb.recordSuccess(probe!); // → CLOSED
    expect(cb.beginRequest()).not.toBeNull();
  });

  it("resets probe flag on recordFailure in HALF_OPEN", () => {
    const cb = new CircuitBreaker({ failureThreshold: 1, cooldownMs: 1000 });
    recordFailure(cb); // → OPEN
    vi.advanceTimersByTime(1000);

    const probe = cb.beginRequest(); // → HALF_OPEN, probe in flight
    cb.recordFailure(probe!); // → OPEN, probe cleared

    // After cooldown, a new probe should be allowed
    vi.advanceTimersByTime(1000);
    expect(cb.beginRequest()).not.toBeNull();
    expect(cb.getState()).toBe("HALF_OPEN");
  });

  it("does not emit stateChange when already in CLOSED and recordSuccess called", () => {
    const cb = new CircuitBreaker();
    const stateChanges: unknown[] = [];
    cb.on("stateChange", (change) => stateChanges.push(change));

    recordSuccess(cb);
    recordSuccess(cb);

    expect(stateChanges).toHaveLength(0);
  });

  it("reset from CLOSED does not emit stateChange", () => {
    const cb = new CircuitBreaker();
    const stateChanges: unknown[] = [];
    cb.on("stateChange", (change) => stateChanges.push(change));

    cb.reset();
    expect(stateChanges).toHaveLength(0);
  });
});
