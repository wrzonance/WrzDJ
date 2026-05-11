import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PreEventVotingTab from "../PreEventVotingTab";
import { apiClient } from "@/lib/api";

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
};

vi.mock("@/lib/api", () => ({
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
    }),
    getPendingReview: vi.fn().mockResolvedValue({ requests: [], total: 0 }),
    bulkReview: vi.fn().mockResolvedValue({ accepted: 0, rejected: 0, unchanged: 0 }),
    syncCollectionToTidal: vi.fn().mockResolvedValue({ queued: 3 }),
  },
}));

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
});
