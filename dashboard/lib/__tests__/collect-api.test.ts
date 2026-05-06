import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { apiClient } from "../api";

const OK_RESPONSE = (body: unknown) =>
  ({ ok: true, status: 200, json: async () => body }) as Response;

const ERR_RESPONSE = (status: number, detail: string) =>
  ({ ok: false, status, json: async () => ({ detail }) }) as Response;

describe("collect api client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // ── credentials policy ────────────────────────────────────────────────────
  // Guest endpoints must include cookies so the server can identify the caller.
  // One consolidated check here; individual happy-path tests focus on return values.

  // Identity-bearing endpoints must send the guest cookie so the server can
  // identify the caller. getCollectProfile is representative; it tracks
  // submission counts and nickname which require guest identity.
  it("identity-bearing endpoints send credentials: include", async () => {
    const profile = { nickname: "DJ", email_verified: false, submission_count: 0, submission_cap: 15 };
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(OK_RESPONSE(profile));
    await apiClient.getCollectProfile("ABC");
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect((opts as RequestInit).credentials).toBe("include");
  });

  // ── getCollectEvent ───────────────────────────────────────────────────────

  it("getCollectEvent returns parsed event data", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ code: "ABC", phase: "collection" })
    );
    const r = await apiClient.getCollectEvent("ABC");
    expect(r.phase).toBe("collection");
    expect(r.code).toBe("ABC");
  });

  // ── submitCollectRequest ──────────────────────────────────────────────────

  it("submitCollectRequest returns is_duplicate flag", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ id: 7, is_duplicate: true })
    );
    const r = await apiClient.submitCollectRequest("ABC", {
      song_title: "T",
      artist: "A",
      source: "spotify",
    });
    expect(r.is_duplicate).toBe(true);
    expect(r.id).toBe(7);
  });

  it("submitCollectRequest throws ApiError on 409", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      ERR_RESPONSE(409, "You already picked this one!")
    );
    await expect(
      apiClient.submitCollectRequest("ABC", {
        song_title: "T",
        artist: "A",
        source: "spotify",
      })
    ).rejects.toThrow("You already picked this one!");
  });

  // ── voteCollectRequest ────────────────────────────────────────────────────

  it("voteCollectRequest sends the request_id in request body", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ ok: true })
    );
    await apiClient.voteCollectRequest("ABC", 99);
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({ request_id: 99 });
  });

  it("voteCollectRequest throws ApiError with detail on 409", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      ERR_RESPONSE(409, "Can't vote on your own pick")
    );
    await expect(apiClient.voteCollectRequest("ABC", 99)).rejects.toThrow(
      "Can't vote on your own pick"
    );
  });

  // ── getCollectProfile ─────────────────────────────────────────────────────

  it("getCollectProfile returns profile data", async () => {
    const profile = { nickname: "DJ", email_verified: true, submission_count: 3, submission_cap: 15 };
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(OK_RESPONSE(profile));
    const r = await apiClient.getCollectProfile("ABC");
    expect(r.email_verified).toBe(true);
    expect(r.nickname).toBe("DJ");
  });

  // ── checkHasRequested ─────────────────────────────────────────────────────

  it("checkHasRequested returns has_requested flag", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ has_requested: true })
    );
    const r = await apiClient.checkHasRequested("ABC");
    expect(r.has_requested).toBe(true);
  });
});
