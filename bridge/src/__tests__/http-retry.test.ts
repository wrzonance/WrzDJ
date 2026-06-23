/**
 * Tests for the shared HTTP retry/backoff/timeout primitives.
 *
 * These pin the contract that BOTH bridge artifacts depend on — the headless
 * bridge (`bridge/src/bridge.ts`) and the Electron bridge app
 * (`bridge-app/src/main/bridge-runner.ts`). Drift in any constant or in the
 * backoff math silently changes retry behavior in both consumers, so the values
 * and progressions are asserted exactly.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  MAX_RETRIES,
  INITIAL_BACKOFF_MS,
  FETCH_TIMEOUT_MS,
  DELETE_MAX_RETRIES,
  DELETE_BACKOFF_MS,
  computeBackoff,
  sleep,
  fetchWithTimeout,
} from "../http-retry.js";

describe("http-retry constants", () => {
  it("pins the exact contract values both consumers depend on", () => {
    expect(MAX_RETRIES).toBe(3);
    expect(INITIAL_BACKOFF_MS).toBe(2000);
    expect(FETCH_TIMEOUT_MS).toBe(10_000);
    expect(DELETE_MAX_RETRIES).toBe(2);
    expect(DELETE_BACKOFF_MS).toBe(1000);
  });
});

describe("computeBackoff", () => {
  it("doubles the POST backoff per attempt (no jitter, no cap)", () => {
    expect(computeBackoff(INITIAL_BACKOFF_MS, 0)).toBe(2000);
    expect(computeBackoff(INITIAL_BACKOFF_MS, 1)).toBe(4000);
    expect(computeBackoff(INITIAL_BACKOFF_MS, 2)).toBe(8000);
  });

  it("doubles the DELETE backoff per attempt (no jitter, no cap)", () => {
    expect(computeBackoff(DELETE_BACKOFF_MS, 0)).toBe(1000);
    expect(computeBackoff(DELETE_BACKOFF_MS, 1)).toBe(2000);
  });

  it("returns the base unchanged at attempt 0 for any base", () => {
    expect(computeBackoff(500, 0)).toBe(500);
    expect(computeBackoff(3000, 3)).toBe(24_000);
  });
});

describe("sleep", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves only after the given number of milliseconds", async () => {
    let resolved = false;
    const promise = sleep(2000).then(() => {
      resolved = true;
    });

    // Not yet — short of the deadline.
    await vi.advanceTimersByTimeAsync(1999);
    expect(resolved).toBe(false);

    // Crossing the deadline resolves it.
    await vi.advanceTimersByTimeAsync(1);
    await promise;
    expect(resolved).toBe(true);
  });
});

describe("fetchWithTimeout", () => {
  const realFetch = global.fetch;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    global.fetch = realFetch;
  });

  it("passes the AbortController signal through to fetch and returns its response", async () => {
    let seenSignal: AbortSignal | undefined;
    const response = { ok: true, status: 200 } as Response;
    global.fetch = vi.fn(async (_url: string | URL | Request, options?: RequestInit) => {
      seenSignal = options?.signal ?? undefined;
      return response;
    }) as unknown as typeof fetch;

    const result = await fetchWithTimeout("https://api.wrzdj.com/x", { method: "POST" });

    expect(result).toBe(response);
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal?.aborted).toBe(false);
  });

  it("aborts the fetch at FETCH_TIMEOUT_MS when the request never resolves", async () => {
    let capturedSignal: AbortSignal | undefined;
    // Reject when the signal fires (mirrors fetch's real AbortError behavior).
    global.fetch = vi.fn(
      (_url: string | URL | Request, options?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          capturedSignal = options?.signal ?? undefined;
          capturedSignal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        }),
    ) as unknown as typeof fetch;

    const pending = fetchWithTimeout("https://api.wrzdj.com/x", { method: "POST" });
    // Surface the rejection so the unhandled-rejection guard stays quiet.
    const settled = pending.then(
      () => ({ ok: true as const }),
      (err: Error) => ({ ok: false as const, err }),
    );

    // Just short of the timeout: still pending, not aborted.
    await vi.advanceTimersByTimeAsync(FETCH_TIMEOUT_MS - 1);
    expect(capturedSignal?.aborted).toBe(false);

    // Crossing FETCH_TIMEOUT_MS fires the abort and rejects the fetch.
    await vi.advanceTimersByTimeAsync(1);
    const outcome = await settled;
    expect(outcome.ok).toBe(false);
    expect(capturedSignal?.aborted).toBe(true);
    if (!outcome.ok) {
      expect(outcome.err.name).toBe("AbortError");
    }
  });

  it("honors a caller-supplied timeout override", async () => {
    let capturedSignal: AbortSignal | undefined;
    global.fetch = vi.fn(
      (_url: string | URL | Request, options?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          capturedSignal = options?.signal ?? undefined;
          capturedSignal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        }),
    ) as unknown as typeof fetch;

    const settled = fetchWithTimeout("https://api.wrzdj.com/x", { method: "GET" }, 500).then(
      () => ({ ok: true as const }),
      (err: Error) => ({ ok: false as const, err }),
    );

    // Default timeout would NOT have fired yet, but the 500ms override has.
    await vi.advanceTimersByTimeAsync(500);
    const outcome = await settled;
    expect(outcome.ok).toBe(false);
    expect(capturedSignal?.aborted).toBe(true);
  });

  it("clears the timeout timer once fetch resolves (no leak, no late abort)", async () => {
    // Capture the controller the function constructs so we can prove it is never
    // aborted after the fetch settles.
    let capturedSignal: AbortSignal | undefined;
    global.fetch = vi.fn(async (_url: string | URL | Request, options?: RequestInit) => {
      capturedSignal = options?.signal ?? undefined;
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;

    const setSpy = vi.spyOn(global, "setTimeout");
    const clearSpy = vi.spyOn(global, "clearTimeout");

    await fetchWithTimeout("https://api.wrzdj.com/x", { method: "POST" });

    // The single timeout scheduled by fetchWithTimeout was cleared in `finally`.
    expect(setSpy).toHaveBeenCalledTimes(1);
    const timeoutId = setSpy.mock.results[0]?.value;
    expect(clearSpy).toHaveBeenCalledWith(timeoutId);

    // And advancing well past FETCH_TIMEOUT_MS must NOT fire a late abort on the
    // already-settled request.
    await vi.advanceTimersByTimeAsync(FETCH_TIMEOUT_MS * 2);
    expect(capturedSignal?.aborted).toBe(false);

    setSpy.mockRestore();
    clearSpy.mockRestore();
  });
});
