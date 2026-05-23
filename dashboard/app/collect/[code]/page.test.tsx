import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { useEffect } from "react";
import type React from "react";
import CollectPage from "./page";

vi.mock("./components/EmailVerification", () => ({
  default: () => <div data-testid="email-verification-stub" />,
}));

// EmailGate wraps the page; stub as passthrough so tests don't render the
// Turnstile-driven EmailVerification subtree (which spins up effects against
// a non-existent window.turnstile in jsdom). The real gate is exercised in
// dedicated EmailGate tests.
vi.mock("../../../components/EmailGate", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/useHumanVerification", () => ({
  useHumanVerification: () => ({
    state: 'verified',
    reverify: vi.fn().mockResolvedValue(undefined),
    ensureVerified: vi.fn().mockResolvedValue(undefined),
    widgetContainerRef: { current: null },
  }),
}));

vi.mock("../../../components/NicknameGate", () => ({
  NicknameGate: ({ onComplete }: { onComplete: (r: { nickname: string; emailVerified: boolean; submissionCount: number; submissionCap: number }) => void }) => {
    useEffect(() => {
      onComplete({ nickname: '', emailVerified: false, submissionCount: 0, submissionCap: 15 });
    }, []);  
    return null;
  },
}));

vi.mock("../../../components/IdentityBar", () => ({
  IdentityBar: () => <div data-testid="identity-bar-stub" />,
}));

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
  useParams: () => ({ code: "ABC" }),
}));

const mockGetEvent = vi.fn();
const mockGetCollectProfile = vi.fn();
const mockGetCollectLeaderboard = vi.fn();
const mockSubmitCollectRequest = vi.fn();
const mockEventSearch = vi.fn();
const mockEnrichPreview = vi.fn();
const mockGetLiveJoinCode = vi.fn().mockResolvedValue({ join_code: "ABC" });

vi.mock("../../../lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  apiClient: {
    getCollectEvent: (...a: unknown[]) => mockGetEvent(...a),
    getCollectLeaderboard: (...a: unknown[]) => mockGetCollectLeaderboard(...a),
    getCollectMyPicks: vi.fn().mockResolvedValue({
      submitted: [], upvoted: [], is_top_contributor: false, first_suggestion_ids: [], voted_request_ids: []
    }),
    getCollectProfile: (...a: unknown[]) => mockGetCollectProfile(...a),
    submitCollectRequest: (...a: unknown[]) => mockSubmitCollectRequest(...a),
    eventSearch: (...a: unknown[]) => mockEventSearch(...a),
    search: vi.fn().mockResolvedValue([]),
    voteCollectRequest: vi.fn().mockResolvedValue(undefined),
    enrichPreview: (...a: unknown[]) => mockEnrichPreview(...a),
    getLiveJoinCode: (...a: unknown[]) => mockGetLiveJoinCode(...a),
  },
}));

const COLLECTION_EVENT = {
  code: "ABC",
  name: "Test Event",
  phase: "collection" as const,
  collection_opens_at: new Date(Date.now() - 3600_000).toISOString(),
  live_starts_at: new Date(Date.now() + 3600_000).toISOString(),
  submission_cap_per_guest: 15,
  banner_filename: null,
  registration_enabled: true,
  expires_at: new Date(Date.now() + 86400_000).toISOString(),
};

describe("CollectPage", () => {
  beforeEach(() => {
    mockReplace.mockClear();
    mockGetEvent.mockReset();
    mockEnrichPreview.mockReset();
    const defaultProfile = {
      email_verified: false,
      nickname: null,
      submission_count: 0,
      submission_cap: 15,
    };
    mockGetCollectProfile.mockResolvedValue(defaultProfile);
    mockGetCollectLeaderboard.mockResolvedValue({ requests: [], total: 0 });
    mockSubmitCollectRequest.mockResolvedValue({ id: 42 });
    mockEventSearch.mockResolvedValue([]);
    mockEnrichPreview.mockResolvedValue([]);
    vi.stubGlobal("sessionStorage", {
      getItem: vi.fn(),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    vi.stubGlobal("localStorage", {
      getItem: vi.fn().mockReturnValue(null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows pre-announce countdown when phase is pre_announce", async () => {
    mockGetEvent.mockResolvedValue({
      code: "ABC",
      name: "Test Event",
      phase: "pre_announce",
      collection_opens_at: new Date(Date.now() + 3600_000).toISOString(),
      live_starts_at: new Date(Date.now() + 7200_000).toISOString(),
      submission_cap_per_guest: 15,
      banner_filename: null,
      registration_enabled: true,
      expires_at: new Date(Date.now() + 86400_000).toISOString(),
    });
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/until voting opens/i)).toBeInTheDocument();
    });
  });

  it("renders collection experience when phase is collection", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/test event/i)).toBeInTheDocument();
    });
  });

  it("redirects to /join when phase is live", async () => {
    mockGetEvent.mockResolvedValue({
      code: "ABC",
      name: "Test Event",
      phase: "live",
      collection_opens_at: new Date(Date.now() - 86400_000).toISOString(),
      live_starts_at: new Date(Date.now() - 3600_000).toISOString(),
      submission_cap_per_guest: 15,
      banner_filename: null,
      registration_enabled: true,
      expires_at: new Date(Date.now() + 86400_000).toISOString(),
    });
    render(<CollectPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/join/ABC");
    });
    expect(sessionStorage.setItem).toHaveBeenCalledWith(
      "wrzdj_live_splash_ABC",
      "1"
    );
  });

  it("IdentityBar renders after gate completes", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/test event/i)).toBeInTheDocument();
    });
    // IdentityBar is rendered (mocked as identity-bar-stub) once gate completes.
    // The NicknameGate mock fires onComplete with empty nickname so IdentityBar
    // should NOT render (nickname is falsy).
    expect(screen.queryByTestId("identity-bar-stub")).not.toBeInTheDocument();
  });

  it("calls submitCollectRequest and refreshes profile after track select", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);

    // Initial profile load goes through getCollectProfile; post-submit refresh
    // also hits getCollectProfile (not setCollectProfile) now that reads and
    // writes have separate endpoints.
    mockGetCollectProfile
      .mockResolvedValueOnce({
        email_verified: false,
        nickname: null,
        submission_count: 0,
        submission_cap: 15,
      })
      .mockResolvedValueOnce({
        email_verified: false,
        nickname: null,
        submission_count: 1,
        submission_cap: 15,
      });

    mockSubmitCollectRequest.mockResolvedValue({ id: 42 });

    const track = {
      artist: "Daft Punk",
      title: "Harder Better Faster Stronger",
      album: null,
      popularity: 90,
      spotify_id: "spotify-123",
      album_art: null,
      preview_url: null,
      url: "https://open.spotify.com/track/spotify-123",
      source: "spotify" as const,
      genre: null,
      bpm: null,
      key: null,
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);

    render(<CollectPage />);

    // Wait for collection phase to render the SubmitBar
    await waitFor(() => {
      expect(screen.getByText(/Request a song/i)).toBeInTheDocument();
    });

    // Open search modal
    fireEvent.click(screen.getByText(/Request a song/i));

    await waitFor(() => {
      expect(screen.getByTestId("collect-search-input")).toBeInTheDocument();
    });

    // Type query and search
    fireEvent.change(screen.getByTestId("collect-search-input"), {
      target: { value: "Daft Punk" },
    });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);

    // Wait for result to appear
    await waitFor(() => {
      expect(screen.getByTestId("collect-search-result")).toBeInTheDocument();
    });

    // Click the result to submit
    fireEvent.click(screen.getByTestId("collect-search-result"));

    await waitFor(() => {
      expect(mockSubmitCollectRequest).toHaveBeenCalledWith("ABC", {
        song_title: track.title,
        artist: track.artist,
        source: track.source,
        source_url: track.url,
        artwork_url: undefined,
        nickname: undefined,
      }, expect.any(Function));
    });

    // Profile should have been refreshed after submit (via getCollectProfile).
    // The initial load is now handled by NicknameGate (mocked), so only the
    // post-submit refresh counts here.
    expect(mockGetCollectProfile.mock.calls.length).toBeGreaterThanOrEqual(1);
  });

  it("shows error message when API throws during event fetch", async () => {
    mockGetEvent.mockRejectedValue(new Error("Network failure"));
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/error:/i)).toBeInTheDocument();
    });
  });

  it("shows loading state when event is not yet loaded", async () => {
    // Never resolves so page stays in loading
    mockGetEvent.mockReturnValue(new Promise(() => {}));
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });
  });

  it("redirects to /join when phase is closed", async () => {
    mockGetEvent.mockResolvedValue({
      code: "ABC",
      name: "Test Event",
      phase: "closed",
      collection_opens_at: new Date(Date.now() - 86400_000).toISOString(),
      live_starts_at: new Date(Date.now() - 3600_000).toISOString(),
      submission_cap_per_guest: 15,
      banner_filename: null,
      registration_enabled: true,
      expires_at: new Date(Date.now() + 86400_000).toISOString(),
    });
    render(<CollectPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/join/ABC");
    });
  });

  it("shows 'Picks limit reached' when submit returns 429", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);

    const ApiErrorClass = (await import("../../../lib/api")).ApiError;
    mockSubmitCollectRequest.mockRejectedValue(new ApiErrorClass("rate limited", 429));

    const track = {
      artist: "Avicii",
      title: "Levels",
      album: null,
      popularity: 80,
      spotify_id: "sp-1",
      album_art: null,
      preview_url: null,
      url: "https://open.spotify.com/track/sp-1",
      source: "spotify" as const,
      genre: null,
      bpm: null,
      key: null,
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);

    render(<CollectPage />);
    await waitFor(() => expect(screen.getByText(/Request a song/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Request a song/i));
    await waitFor(() => expect(screen.getByTestId("collect-search-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("collect-search-input"), { target: { value: "Avicii" } });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("collect-search-result")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("collect-search-result"));
    await waitFor(() => expect(screen.getByText(/Picks limit reached/i)).toBeInTheDocument());
  });

  it("shows 'You already picked this one!' when submit returns 409", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);

    const ApiErrorClass = (await import("../../../lib/api")).ApiError;
    mockSubmitCollectRequest.mockRejectedValue(new ApiErrorClass("conflict", 409));

    const track = {
      artist: "Avicii",
      title: "Levels",
      album: null,
      popularity: 80,
      spotify_id: "sp-1",
      album_art: null,
      preview_url: null,
      url: null,
      source: "spotify" as const,
      genre: null,
      bpm: null,
      key: null,
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);

    render(<CollectPage />);
    await waitFor(() => expect(screen.getByText(/Request a song/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Request a song/i));
    await waitFor(() => expect(screen.getByTestId("collect-search-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("collect-search-input"), { target: { value: "Avicii" } });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("collect-search-result")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("collect-search-result"));
    await waitFor(() => expect(screen.getByText(/already picked/i)).toBeInTheDocument());
  });

  it("shows generic error when submit fails with unexpected error", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);
    mockSubmitCollectRequest.mockRejectedValue(new Error("unexpected"));

    const track = {
      artist: "Avicii",
      title: "Levels",
      album: null,
      popularity: 80,
      spotify_id: "sp-2",
      album_art: "https://img.example.com/art.jpg",
      preview_url: null,
      url: "https://open.spotify.com/track/sp-2",
      source: "spotify" as const,
      genre: null,
      bpm: null,
      key: null,
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);

    render(<CollectPage />);
    await waitFor(() => expect(screen.getByText(/Request a song/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Request a song/i));
    await waitFor(() => expect(screen.getByTestId("collect-search-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("collect-search-input"), { target: { value: "Avicii" } });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("collect-search-result")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("collect-search-result"));
    await waitFor(() => expect(screen.getByText(/Failed to submit/i)).toBeInTheDocument());
  });

  it("stays open and shows message when submit is a duplicate", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);
    mockSubmitCollectRequest.mockResolvedValue({ id: 99, is_duplicate: true });
    mockGetCollectProfile.mockResolvedValue({
      email_verified: false,
      nickname: null,
      submission_count: 1,
      submission_cap: 15,
    });

    const track = {
      artist: "Avicii",
      title: "Levels",
      album: null,
      popularity: 80,
      spotify_id: "sp-dup",
      album_art: null,
      preview_url: null,
      url: null,
      source: "spotify" as const,
      genre: null,
      bpm: null,
      key: null,
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);

    render(<CollectPage />);
    await waitFor(() => expect(screen.getByText(/Request a song/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Request a song/i));
    await waitFor(() => expect(screen.getByTestId("collect-search-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("collect-search-input"), { target: { value: "Avicii" } });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("collect-search-result")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("collect-search-result"));
    await waitFor(() => expect(screen.getByText(/great minds/i)).toBeInTheDocument());
    // Search modal should remain open (not closed for duplicate)
    expect(screen.getByTestId("collect-search-input")).toBeInTheDocument();
  });

  it("shows HIGHLIGHT BY VIBES button when search results exist", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);

    const track = {
      artist: "Avicii",
      title: "Levels",
      album: null,
      popularity: 80,
      spotify_id: "sp-v1",
      album_art: null,
      preview_url: null,
      url: null,
      source: "spotify" as const,
      genre: null,
      bpm: 128,
      key: "8A",
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);
    mockEnrichPreview.mockResolvedValue([{ bpm: 128, key: "8A", genre: "House" }]);

    render(<CollectPage />);
    await waitFor(() => expect(screen.getByText(/Request a song/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Request a song/i));
    await waitFor(() => expect(screen.getByTestId("collect-search-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("collect-search-input"), { target: { value: "Avicii" } });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);
    await waitFor(() => expect(screen.getByText(/HIGHLIGHT BY VIBES/i)).toBeInTheDocument());

    // Toggle vibes on — track already has bpm so no enrichment call needed
    fireEvent.click(screen.getByText(/HIGHLIGHT BY VIBES/i));
    await waitFor(() => {
      // The button stays rendered (vibes active)
      expect(screen.getByText(/HIGHLIGHT BY VIBES/i)).toBeInTheDocument();
    });

    // Toggle vibes off
    fireEvent.click(screen.getByText(/HIGHLIGHT BY VIBES/i));
    await waitFor(() => {
      expect(screen.getByText(/HIGHLIGHT BY VIBES/i)).toBeInTheDocument();
    });
  });

  it("calls enrichPreview when vibes toggled and results lack bpm", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);

    const track = {
      artist: "Avicii",
      title: "Levels",
      album: null,
      popularity: 80,
      spotify_id: "sp-v2",
      album_art: null,
      preview_url: null,
      url: "https://open.spotify.com/track/sp-v2",
      source: "spotify" as const,
      genre: null,
      bpm: null,
      key: null,
      isrc: null,
    };
    mockEventSearch.mockResolvedValue([track]);
    mockEnrichPreview.mockResolvedValue([{ bpm: 130, key: "9A", genre: "Trance" }]);

    render(<CollectPage />);
    await waitFor(() => expect(screen.getByText(/Request a song/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Request a song/i));
    await waitFor(() => expect(screen.getByTestId("collect-search-input")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("collect-search-input"), { target: { value: "Avicii" } });
    fireEvent.submit(screen.getByTestId("collect-search-input").closest("form")!);
    await waitFor(() => expect(screen.getByText(/HIGHLIGHT BY VIBES/i)).toBeInTheDocument());

    fireEvent.click(screen.getByText(/HIGHLIGHT BY VIBES/i));
    await waitFor(() => {
      expect(mockEnrichPreview).toHaveBeenCalled();
    });
  });

  it("renders pre_announce phase with collection_opens_at in the past", async () => {
    mockGetEvent.mockResolvedValue({
      code: "ABC",
      name: "Past Open Event",
      phase: "pre_announce",
      collection_opens_at: null,
      live_starts_at: new Date(Date.now() + 7200_000).toISOString(),
      submission_cap_per_guest: 15,
      banner_filename: null,
      registration_enabled: true,
      expires_at: new Date(Date.now() + 86400_000).toISOString(),
    });
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/until voting opens/i)).toBeInTheDocument();
    });
  });

  it("renders collection phase with banner_url", async () => {
    mockGetEvent.mockResolvedValue({
      ...COLLECTION_EVENT,
      banner_url: "https://example.com/banner.jpg",
    });
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText(/test event/i)).toBeInTheDocument();
    });
  });

  it("shows event song count from leaderboard", async () => {
    mockGetEvent.mockResolvedValue(COLLECTION_EVENT);
    mockGetCollectLeaderboard.mockResolvedValue({
      requests: [
        { id: 1, title: "Unique Song Alpha", artist: "Artist A", artwork_url: null, vote_count: 5, nickname: null, status: "new", created_at: new Date().toISOString(), bpm: 128, musical_key: "8A", genre: "House" },
        { id: 2, title: "Unique Song Beta", artist: "Artist B", artwork_url: null, vote_count: 3, nickname: null, status: "new", created_at: new Date().toISOString(), bpm: 140, musical_key: "4A", genre: "Trance" },
      ],
      total: 2,
    });
    render(<CollectPage />);
    await waitFor(() => {
      expect(screen.getByText("Unique Song Alpha")).toBeInTheDocument();
      expect(screen.getByText("Unique Song Beta")).toBeInTheDocument();
    });
  });
});
