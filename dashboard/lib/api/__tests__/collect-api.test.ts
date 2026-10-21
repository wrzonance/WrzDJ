import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { api } from "..";

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
    await api.getCollectProfile("ABC");
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect((opts as RequestInit).credentials).toBe("include");
  });

  // ── getCollectEvent ───────────────────────────────────────────────────────

  it("getCollectEvent returns parsed event data", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ code: "ABC", phase: "collection" })
    );
    const r = await api.getCollectEvent("ABC");
    expect(r.phase).toBe("collection");
    expect(r.code).toBe("ABC");
  });

  // ── submitCollectRequest ──────────────────────────────────────────────────

  it("submitCollectRequest returns is_duplicate flag", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ id: 7, is_duplicate: true })
    );
    const r = await api.submitCollectRequest("ABC", {
      song_title: "T",
      artist: "A",
      source: "spotify",
    });
    expect(r.is_duplicate).toBe(true);
    expect(r.id).toBe(7);
  });

  it("submitCollectRequest forwards the search-result ISRC (#552)", async () => {
    const mock = fetch as unknown as ReturnType<typeof vi.fn>;
    mock.mockResolvedValue(OK_RESPONSE({ id: 8, is_duplicate: false }));
    await api.submitCollectRequest("ABC", {
      song_title: "Strobe",
      artist: "deadmau5",
      source: "beatport",
      isrc: "USXYZ1234567",
    });
    const [, opts] = mock.mock.calls[0];
    expect(JSON.parse((opts as RequestInit).body as string).isrc).toBe("USXYZ1234567");
  });

  it("submitCollectRequest throws ApiError on 409", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      ERR_RESPONSE(409, "You already picked this one!")
    );
    await expect(
      api.submitCollectRequest("ABC", {
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
    await api.voteCollectRequest("ABC", 99);
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({ request_id: 99 });
  });

  it("voteCollectRequest throws ApiError with detail on 409", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      ERR_RESPONSE(409, "Can't vote on your own pick")
    );
    await expect(api.voteCollectRequest("ABC", 99)).rejects.toThrow(
      "Can't vote on your own pick"
    );
  });

  it("voteCollectRequest discards the retried response body after verification", async () => {
    const mock = fetch as unknown as ReturnType<typeof vi.fn>;
    const verificationRequired = {
      ok: false,
      status: 403,
      json: async () => ({ detail: { code: "human_verification_required" } }),
      clone() { return this; },
    } as Response;
    mock.mockResolvedValueOnce(verificationRequired).mockResolvedValueOnce(
      OK_RESPONSE({ ok: true })
    );

    const reverify = vi.fn().mockResolvedValue(undefined);
    await expect(api.voteCollectRequest("ABC", 99, reverify)).resolves.toBeUndefined();
    expect(reverify).toHaveBeenCalledOnce();
    expect(mock).toHaveBeenCalledTimes(2);
  });

  // ── getCollectProfile ─────────────────────────────────────────────────────

  it("getCollectProfile returns profile data", async () => {
    const profile = { nickname: "DJ", email_verified: true, submission_count: 3, submission_cap: 15 };
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(OK_RESPONSE(profile));
    const r = await api.getCollectProfile("ABC");
    expect(r.email_verified).toBe(true);
    expect(r.nickname).toBe("DJ");
  });

  // Regression (#874): an email merge leaves wrzdj_human bound to a guest that
  // no longer exists. The profile load is gated like every other collect call,
  // so it must re-verify and retry once instead of surfacing a dead 403.
  it("getCollectProfile re-verifies and retries once on 403 human_verification_required", async () => {
    const profile = { nickname: "DJ", email_verified: true, submission_count: 3, submission_cap: 15 };
    const stale403 = new Response(
      JSON.stringify({ detail: { code: "human_verification_required" } }),
      { status: 403 },
    );
    (fetch as unknown as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(stale403)
      .mockResolvedValueOnce(OK_RESPONSE(profile));
    const reverify = vi.fn().mockResolvedValue(undefined);

    const r = await api.getCollectProfile("ABC", reverify);

    expect(reverify).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(r.nickname).toBe("DJ");
  });

  it("enrichPreview preserves input identity and accepts null track metadata", async () => {
    const items = [
      { title: "First track", artist: "First artist" },
      { title: "Second track", artist: "Second artist" },
    ];
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(OK_RESPONSE({
      results: [
        { title: "First track", artist: "First artist", bpm: null, key: null, genre: null },
        { title: "Second track", artist: "Second artist", bpm: 128, key: "8A", genre: "House" },
      ],
    }));

    await expect(api.enrichPreview("ABC", items)).resolves.toEqual([
      { ...items[0], bpm: null, key: null, genre: null },
      { ...items[1], bpm: 128, key: "8A", genre: "House" },
    ]);
  });

  it.each([
    ["HTTP failure", () => Promise.resolve(ERR_RESPONSE(503, "private backend detail"))],
    ["network failure", () => Promise.reject(new Error("fetch failed for secret URL"))],
    ["malformed JSON", () => Promise.resolve({ ok: true, status: 200, json: async () => { throw new Error("private parse detail"); } })],
    ["missing result list", () => Promise.resolve(OK_RESPONSE({ results: null }))],
    ["short result list", () => Promise.resolve(OK_RESPONSE({ results: [] }))],
    ["reordered track identities", () => Promise.resolve(OK_RESPONSE({
      results: [
        { title: "Second track", artist: "Second artist", bpm: 128, key: "8A", genre: "House" },
        { title: "First track", artist: "First artist", bpm: 90, key: "1A", genre: "Rock" },
      ],
    }))],
  ])("enrichPreview rejects %s without leaking transport details", async (_case, response) => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(response);
    await expect(api.enrichPreview("ABC", [
      { title: "First track", artist: "First artist" },
      { title: "Second track", artist: "Second artist" },
    ])).rejects.toThrow("Preview enrichment is temporarily unavailable. Please try again.");
  });

  // ── checkHasRequested ─────────────────────────────────────────────────────

  it("checkHasRequested returns has_requested flag", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      OK_RESPONSE({ has_requested: true })
    );
    const r = await api.checkHasRequested("ABC");
    expect(r.has_requested).toBe(true);
  });
});
