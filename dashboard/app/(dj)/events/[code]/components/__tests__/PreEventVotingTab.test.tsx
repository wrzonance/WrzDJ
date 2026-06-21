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

  // ---- Client-side load-all + sort (issue #489) ----

  it("loads the full set in default Review order (no sort param)", async () => {
    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => {
      // Chunked loader pages from offset 0 at PUBLIC_PAGE_MAX with no sort param.
      expect(apiClient.getPendingReview).toHaveBeenCalledWith("ABC", {
        limit: PUBLIC_PAGE_MAX,
        offset: 0,
      });
    });
  });

  it("sorts a simple field in memory without a re-fetch", async () => {
    vi.mocked(apiClient.getPendingReview).mockResolvedValue(
      // Vote-ranked server order: 3, 2, 1.
      envelope([makeRow(3), makeRow(2), makeRow(1)], 3)
    );

    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getByText("Song 3")).toBeInTheDocument());
    const callsAfterLoad = vi.mocked(apiClient.getPendingReview).mock.calls.length;

    // Sort by Title ascending → "Song 1" before "Song 2" before "Song 3".
    fireEvent.change(screen.getByLabelText(/sort pending review by/i), {
      target: { value: "title" },
    });

    await waitFor(() => {
      const rows = screen.getAllByText(/^Song \d$/).map((el) => el.textContent);
      expect(rows).toEqual(["Song 1", "Song 2", "Song 3"]);
    });
    // No additional network fetch — the sort is purely client-side.
    expect(apiClient.getPendingReview).toHaveBeenCalledTimes(callsAfterLoad);
  });

  it("renders Review order as the server returned it (no client re-sort)", async () => {
    // Server vote-rank order is 2, 3, 1 (not numeric / not title order).
    vi.mocked(apiClient.getPendingReview).mockResolvedValue(
      envelope([makeRow(2), makeRow(3), makeRow(1)], 3)
    );

    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );

    await waitFor(() => expect(screen.getByText("Song 2")).toBeInTheDocument());
    const rows = screen.getAllByText(/^Song \d$/).map((el) => el.textContent);
    expect(rows).toEqual(["Song 2", "Song 3", "Song 1"]);
  });

  it("snaps direction to the field default and toggles it (in memory)", async () => {
    vi.mocked(apiClient.getPendingReview).mockResolvedValue(
      envelope([makeRow(1), makeRow(2), makeRow(3)], 3)
    );

    render(
      <PreEventVotingTab
        event={baseEvent}
        tidalConnected={false}
        tidalIntegrationEnabled={false}
        onEventChange={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getByText("Song 1")).toBeInTheDocument());

    // Title defaults to ascending: Song 1, 2, 3.
    fireEvent.change(screen.getByLabelText(/sort pending review by/i), {
      target: { value: "title" },
    });
    await waitFor(() => {
      const rows = screen.getAllByText(/^Song \d$/).map((el) => el.textContent);
      expect(rows).toEqual(["Song 1", "Song 2", "Song 3"]);
    });

    // Toggle to descending: Song 3, 2, 1.
    fireEvent.click(screen.getByRole("button", { name: /sort direction/i }));
    await waitFor(() => {
      const rows = screen.getAllByText(/^Song \d$/).map((el) => el.textContent);
      expect(rows).toEqual(["Song 3", "Song 2", "Song 1"]);
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

  it("shows 'Showing X of N' and never a Load More button", async () => {
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

  it("shows the cap banner when the set exceeds the 2000-row cap", async () => {
    // total claims 5000 but the loader stops at the 2000 cap; mock a chunk that
    // always returns a full PUBLIC_PAGE_MAX page so the loader reaches the cap.
    vi.mocked(apiClient.getPendingReview).mockImplementation(async (_code, opts) => ({
      requests: Array.from({ length: opts?.limit ?? PUBLIC_PAGE_MAX }, (_, i) =>
        makeRow((opts?.offset ?? 0) + i + 1)
      ),
      total: 5000,
      limit: opts?.limit ?? PUBLIC_PAGE_MAX,
      offset: opts?.offset ?? 0,
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

    await waitFor(() =>
      expect(screen.getByText(/Showing 2000 of 5000 requests/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/sort\/filter limited to these/i)).toBeInTheDocument();
  });
});
