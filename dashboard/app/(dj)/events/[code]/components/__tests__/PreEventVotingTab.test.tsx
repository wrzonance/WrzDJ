import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PreEventVotingTab from "../PreEventVotingTab";
import { apiClient, PUBLIC_PAGE_MAX, type PendingReviewRow } from "@/lib/api";

const baseEvent = {
  code: "ABC",
  name: "Wedding",
  collection_opens_at: "2026-04-21T12:00:00Z",
  live_starts_at: "2026-04-22T20:00:00Z",
  submission_cap_per_guest: 15,
  collection_phase_override: null,
  phase: "collection" as const,
  tidal_sync_enabled: false,
  tidal_collection_playlist_id: null,
  tidal_collection_bidirectional: false,
};

// A full PendingReviewRow literal — every required key present (#478).
function makeRow(id: number): PendingReviewRow {
  return {
    id,
    song_title: `Song ${id}`,
    artist: `Artist ${id}`,
    artwork_url: null,
    vote_count: id,
    nickname: null,
    created_at: "2026-04-21T12:00:00Z",
    note: null,
    status: "new",
  };
}

// Pending-review envelope (#478): requests + total (+ pagination/sort echo).
function envelope(rows: PendingReviewRow[], total: number) {
  return { requests: rows, total, limit: 100, offset: 0, sort: null, direction: null };
}

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    apiClient: {
      patchCollectionSettings: vi.fn().mockResolvedValue({
        code: "ABC",
        name: "Wedding",
        collection_opens_at: "2026-04-21T12:00:00Z",
        live_starts_at: "2026-04-22T20:00:00Z",
        submission_cap_per_guest: 15,
        collection_phase_override: "force_live",
        phase: "live",
        tidal_sync_enabled: false,
        tidal_collection_playlist_id: null,
        tidal_collection_bidirectional: false,
      }),
      getPendingReview: vi.fn().mockResolvedValue({
        requests: [],
        total: 0,
        limit: 100,
        offset: 0,
        sort: null,
        direction: null,
      }),
      bulkReview: vi.fn().mockResolvedValue({ accepted: 0, rejected: 0, unchanged: 0 }),
      syncCollectionToTidal: vi.fn().mockResolvedValue({ queued: 3 }),
    },
  };
});

beforeEach(() => {
  vi.mocked(apiClient.getPendingReview).mockReset();
  vi.mocked(apiClient.getPendingReview).mockResolvedValue({
    requests: [],
    total: 0,
    limit: 100,
    offset: 0,
    sort: null,
    direction: null,
  });
});

describe("PreEventVotingTab", () => {
  it("renders phase and share link", () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    expect(screen.getByText(/current phase/i)).toBeInTheDocument();
    expect(screen.getAllByText(/collection/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/\/collect\/ABC/i)).toBeInTheDocument();
  });

  it("applies force_live override via button", async () => {
    const onEventChange = vi.fn();
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={onEventChange}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /start live now/i }));
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
    await waitFor(() => {
      expect(onEventChange).toHaveBeenCalled();
    });
  });

  it("hides Tidal section when Tidal not connected", () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={true}
        onEventChange={vi.fn()}
      />
    );
    expect(screen.queryByText(/tidal collection sync/i)).not.toBeInTheDocument();
  });

  it("shows Tidal section when Tidal connected and integration enabled", () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={true}
        tidalIntegrationEnabled={true}
        onEventChange={vi.fn()}
      />
    );
    expect(screen.getByText(/tidal collection sync/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("sync button only visible when tidal_sync_enabled is true", () => {
    render(
      <PreEventVotingTab
        event={{ ...baseEvent, tidal_sync_enabled: true }}
        tidalConnected={true}
        tidalIntegrationEnabled={true}
        onEventChange={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: /sync collection to tidal/i })).toBeInTheDocument();
  });

  it("sync button hidden when tidal_sync_enabled is false", () => {
    render(
      <PreEventVotingTab
        event={{ ...baseEvent, tidal_sync_enabled: false }}
        tidalConnected={true}
        tidalIntegrationEnabled={true}
        onEventChange={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: /sync collection to tidal/i })).not.toBeInTheDocument();
  });

  it("triggers collection sync when sync button is clicked", async () => {
    render(
      <PreEventVotingTab
        event={{ ...baseEvent, tidal_sync_enabled: true }}
        tidalConnected={true}
        tidalIntegrationEnabled={true}
        onEventChange={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /sync collection to tidal/i }));
    await waitFor(() => {
      expect(apiClient.syncCollectionToTidal).toHaveBeenCalledWith("ABC");
    });
  });

  it("patches tidal_collection_bidirectional when checkbox is toggled", async () => {
    render(
      <PreEventVotingTab
        event={{ ...baseEvent, tidal_sync_enabled: true, tidal_collection_bidirectional: false }}
        tidalConnected={true}
        tidalIntegrationEnabled={true}
        onEventChange={vi.fn()}
      />
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: /songs removed from tidal playlist are auto-rejected/i })
    );
    await waitFor(() => {
      expect(apiClient.patchCollectionSettings).toHaveBeenCalledWith("ABC", {
        tidal_collection_bidirectional: true,
      });
    });
  });

  // ---- Pagination + sort (issue #478) ----

  it("fetches the first page in default Review order (no sort param)", async () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => {
      expect(apiClient.getPendingReview).toHaveBeenCalledWith("ABC", {
        limit: 100,
        offset: 0,
      });
    });
  });

  it("re-fetches with sort + direction when the Sort select changes", async () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => expect(apiClient.getPendingReview).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/sort pending review by/i), {
      target: { value: "upvotes" },
    });

    await waitFor(() => {
      expect(apiClient.getPendingReview).toHaveBeenCalledWith("ABC", {
        sort: "upvotes",
        direction: "desc",
        limit: 100,
        offset: 0,
      });
    });
  });

  it("snaps direction to the field default and toggles it", async () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => expect(apiClient.getPendingReview).toHaveBeenCalled());

    // Title defaults to ascending; the toggle then flips it to descending.
    fireEvent.change(screen.getByLabelText(/sort pending review by/i), {
      target: { value: "title" },
    });
    await waitFor(() => {
      expect(apiClient.getPendingReview).toHaveBeenCalledWith("ABC", {
        sort: "title",
        direction: "asc",
        limit: 100,
        offset: 0,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /sort direction/i }));
    await waitFor(() => {
      expect(apiClient.getPendingReview).toHaveBeenCalledWith("ABC", {
        sort: "title",
        direction: "desc",
        limit: 100,
        offset: 0,
      });
    });
  });

  it("has no direction toggle in Review order", async () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => expect(apiClient.getPendingReview).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /sort direction/i })).not.toBeInTheDocument();
  });

  it("shows 'Showing X of N' from the envelope total and Load More grows the window", async () => {
    vi.mocked(apiClient.getPendingReview)
      .mockResolvedValueOnce(envelope([makeRow(1), makeRow(2)], 250))
      .mockResolvedValueOnce(envelope([makeRow(1), makeRow(2), makeRow(3)], 250));

    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );

    await waitFor(() => expect(screen.getByText(/showing 2 of 250/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /load more/i }));

    // Second call asks for the grown window (limit 200) from offset 0.
    await waitFor(() => {
      expect(apiClient.getPendingReview).toHaveBeenLastCalledWith("ABC", {
        limit: 200,
        offset: 0,
      });
    });
  });

  it("hides Load More once the loaded count reaches the envelope total", async () => {
    vi.mocked(apiClient.getPendingReview).mockResolvedValue(
      envelope([makeRow(1), makeRow(2)], 2)
    );

    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );

    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
  });

  it("clamps the growing window to PUBLIC_PAGE_MAX on Load More", async () => {
    // Enough total to keep Load More alive; we click until the requested limit
    // would exceed the cap and assert it is clamped to PUBLIC_PAGE_MAX. The
    // mock always echoes the requested limit's worth of (one) row so the loaded
    // count never trips the row-length gate — isolating the limit clamp.
    vi.mocked(apiClient.getPendingReview).mockImplementation(async (_code, opts) => ({
      requests: [makeRow(1)],
      total: 100_000,
      limit: opts?.limit ?? 100,
      offset: 0,
      sort: null,
      direction: null,
    }));

    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument());

    // Click Load More many times; the requested limit grows by 100 but clamps.
    // Wait for each click's fetch to actually land (incremental call count),
    // otherwise the loop races ahead and the clamp assertion can false-pass.
    const baseCalls = vi.mocked(apiClient.getPendingReview).mock.calls.length;
    for (let i = 0; i < 10; i++) {
      fireEvent.click(screen.getByRole("button", { name: /load more/i }));
      await waitFor(() =>
        expect(apiClient.getPendingReview).toHaveBeenCalledTimes(baseCalls + i + 1),
      );
    }

    const requestedLimits = vi
      .mocked(apiClient.getPendingReview)
      .mock.calls.map(([, opts]) => opts?.limit ?? 0);
    expect(Math.max(...requestedLimits)).toBeLessThanOrEqual(PUBLIC_PAGE_MAX);
    // The window actually reached the cap rather than stopping short.
    expect(requestedLimits.at(-1)).toBe(PUBLIC_PAGE_MAX);
  });
});
