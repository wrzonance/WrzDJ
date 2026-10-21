import type { AgentChatHistory } from '../types';
import type { ApiTransport } from '../transport';
import { getApiUrl } from '../shared';
import type { AgentChatIn, AgentChatOut, BuildSetResponse, BuilderPlaylists, CollaboratorAccepted, CollaboratorInvite, CollaboratorInviteCreated, ApplyTemplateResponse, CurvePoint, CurveTemplate, CurveTemplatesResponse, Pairing, PairingCreate, PairingUpdate, PairingsState, PlaybackReport, ApplyPairingFeedback, PoolImportManualIn, PoolImportResult, PoolMutationResult, PoolState, PoolUrlPreview, PoolVibeOverrideIn, PoolVibesState, SetCritique, SetDocumentSnapshot, SetDetail, SetSlotOut, SetSummary, SetTemplate, SetTemplateGalleryResponse, SharedSetView, ShareTokenOut, SlotTargetOut, TasteProfile, TransitionScore, TransportCommandIn, TransportCommandOut, TransportStatusOut, VibeEnrichmentResult, VibeWindow, VibeWindowsResponse, ExportTarget, ExportFileFormat, ExportPreflight, ExportTidalResult, ExportSpotifyResult, ExportAppleMusicResult, ExportAppleMusicRecoveryRequest, ExportAppleMusicRecoveryResult } from '../types';

export class SetbuilderApi {
  constructor(public readonly transport: ApiTransport) {}

  async listSets(): Promise<SetSummary[]> {
    return this.transport.fetch('/api/setbuilder/sets');
  }
  async createSet(name: string, eventId?: number): Promise<SetDetail> {
    return this.transport.fetch('/api/setbuilder/sets', {
      method: 'POST',
      body: JSON.stringify({ name, event_id: eventId ?? null }),
    });
  }
  async getSet(setId: number): Promise<SetDetail> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}`);
  }
  async getSetDocument(setId: number): Promise<SetDocumentSnapshot> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/document`);
  }
  async putSetDocument(
    setId: number,
    snapshot: SetDocumentSnapshot
  ): Promise<SetDocumentSnapshot> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/document`, {
      method: 'PUT',
      body: JSON.stringify(snapshot),
    });
  }
  async reorderSlots(setId: number, slotIds: number[]): Promise<TransitionScore[]> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/slots/order`, {
      method: 'PUT',
      body: JSON.stringify({ slot_ids: slotIds }),
    });
  }
  async renameSet(setId: number, name: string): Promise<SetDetail> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }
  async updateSetTargetSettings(
    setId: number,
    targetDurationSec: number | null,
    avgTransitionOverlapSec: number,
  ): Promise<SetDetail> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/target`, {
      method: 'PUT',
      body: JSON.stringify({
        target_duration_sec: targetDurationSec,
        avg_transition_overlap_sec: avgTransitionOverlapSec,
      }),
    });
  }
  async deleteSet(setId: number): Promise<void> {
    await this.transport.rawFetch(`/api/setbuilder/sets/${setId}`, { method: 'DELETE' });
  }
  async getSetbuilderTasteProfile(): Promise<TasteProfile> {
    return this.transport.fetch('/api/setbuilder/taste-profile');
  }
  async resetSetbuilderTasteProfile(): Promise<TasteProfile> {
    return this.transport.fetch('/api/setbuilder/taste-profile/reset', { method: 'POST' });
  }

  // WrzDJSet energy curve editor (#389)
  async getCurveTemplates(): Promise<CurveTemplatesResponse> {
    return this.transport.fetch('/api/setbuilder/curve-templates');
  }
  async createCurveTemplate(name: string, points: CurvePoint[]): Promise<CurveTemplate> {
    return this.transport.fetch('/api/setbuilder/curve-templates', {
      method: 'POST',
      body: JSON.stringify({ name, points }),
    });
  }
  async updateCurveTemplate(
    templateId: number,
    name: string,
    points: CurvePoint[],
  ): Promise<CurveTemplate> {
    return this.transport.fetch(`/api/setbuilder/curve-templates/${templateId}`, {
      method: 'PUT',
      body: JSON.stringify({ name, points }),
    });
  }
  async deleteCurveTemplate(templateId: number): Promise<void> {
    await this.transport.rawFetch(`/api/setbuilder/curve-templates/${templateId}`, { method: 'DELETE' });
  }
  async getSetSlots(setId: number): Promise<SetSlotOut[]> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/slots`);
  }
  async updateSlotTarget(
    setId: number,
    slotId: number,
    targetEnergy: number | null,
  ): Promise<SlotTargetOut> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/slots/${slotId}/target`, {
      method: 'PATCH',
      body: JSON.stringify({ target_energy: targetEnergy }),
    });
  }
  async buildSet(setId: number, confirmed: boolean): Promise<BuildSetResponse> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/build`, {
      method: 'POST',
      body: JSON.stringify({ confirmed }),
    });
  }
  async critiqueSet(setId: number): Promise<SetCritique> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/critique`, { method: 'POST' });
  }
  async getSetAgentHistory(setId: number): Promise<AgentChatHistory> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/agent/history`);
  }
  async chatWithSetAgent(setId: number, payload: AgentChatIn): Promise<AgentChatOut> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/agent/chat`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
  async applyCurveTemplate(
    setId: number,
    source: { builtin?: string; template_id?: number },
    slotMidpoints?: number[],
  ): Promise<ApplyTemplateResponse> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/curve/apply-template`, {
      method: 'POST',
      body: JSON.stringify({ ...source, slot_midpoints: slotMidpoints ?? null }),
    });
  }
  async getVibeWindows(setId: number): Promise<VibeWindowsResponse> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/vibe-windows`);
  }
  async putVibeWindows(setId: number, windows: VibeWindow[]): Promise<VibeWindowsResponse> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/vibe-windows`, {
      method: 'PUT',
      body: JSON.stringify({ windows }),
    });
  }

  // WrzDJSet pairings (issue #392)
  async getPairings(setId: number, query?: string): Promise<PairingsState> {
    const qs = query?.trim() ? `?query=${encodeURIComponent(query.trim())}` : '';
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pairings${qs}`);
  }
  async savePairing(setId: number, pairing: PairingCreate): Promise<Pairing> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pairings`, {
      method: 'POST',
      body: JSON.stringify(pairing),
    });
  }
  async updatePairing(setId: number, pairingId: number, patch: PairingUpdate): Promise<Pairing> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pairings/${pairingId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  }
  async deletePairing(setId: number, pairingId: number): Promise<void> {
    await this.transport.rawFetch(`/api/setbuilder/sets/${setId}/pairings/${pairingId}`, {
      method: 'DELETE',
    });
  }

  // WrzDJSet play-history feedback loop (issue #403)
  async getPlaybackReport(setId: number): Promise<PlaybackReport> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/playback-report`);
  }
  async applyPlaybackPairings(setId: number): Promise<ApplyPairingFeedback> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/playback-report/apply-pairings`, {
      method: 'POST',
    });
  }

  async getTransportStatus(setId: number): Promise<TransportStatusOut> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/transport/status`);
  }

  async sendTransportCommand(
    setId: number,
    payload: TransportCommandIn,
  ): Promise<TransportCommandOut> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/transport/command`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // WrzDJSet pool (issue #388)
  async getPool(setId: number): Promise<PoolState> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool`);
  }
  // TrackVibe three-tier state (issue #391)
  async getPoolVibes(setId: number): Promise<PoolVibesState> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/vibes`);
  }
  async enrichPoolVibes(setId: number): Promise<VibeEnrichmentResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/vibes/enrich`, { method: 'POST' });
  }
  async agreePoolVibe(setId: number, poolTrackId: number): Promise<PoolVibesState> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/vibes/${poolTrackId}/agree`, {
      method: 'POST',
    });
  }
  async overridePoolVibe(
    setId: number,
    poolTrackId: number,
    payload: PoolVibeOverrideIn
  ): Promise<PoolVibesState> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/vibes/${poolTrackId}/override`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }
  async getBuilderPlaylists(): Promise<BuilderPlaylists> {
    return this.transport.fetch('/api/setbuilder/playlists');
  }
  async importPoolEvent(setId: number, eventId: number): Promise<PoolImportResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/import/event`, {
      method: 'POST',
      body: JSON.stringify({ event_id: eventId }),
    });
  }
  async importPoolTidal(
    setId: number,
    playlistId: string,
    label?: string
  ): Promise<PoolImportResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/import/tidal`, {
      method: 'POST',
      body: JSON.stringify({ playlist_id: playlistId, label: label ?? null }),
    });
  }
  async importPoolBeatport(
    setId: number,
    playlistId: string,
    label?: string
  ): Promise<PoolImportResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/import/beatport`, {
      method: 'POST',
      body: JSON.stringify({ playlist_id: playlistId, label: label ?? null }),
    });
  }
  async previewPoolUrl(setId: number, url: string): Promise<PoolUrlPreview> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/url-preview`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  }
  async importPoolUrl(setId: number, url: string): Promise<PoolImportResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/import/url`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  }
  async importPoolManual(setId: number, track: PoolImportManualIn): Promise<PoolImportResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/import/manual`, {
      method: 'POST',
      body: JSON.stringify(track),
    });
  }
  async removePoolTracks(setId: number, trackIds: number[]): Promise<PoolMutationResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/tracks/remove`, {
      method: 'POST',
      body: JSON.stringify({ track_ids: trackIds }),
    });
  }
  async removePoolSource(setId: number, sourceId: number): Promise<PoolMutationResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/pool/sources/${sourceId}`, {
      method: 'DELETE',
    });
  }

  // WrzDJSet sharing + duplication (issue #398)
  async duplicateSet(setId: number): Promise<SetDetail> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/duplicate`, { method: 'POST' });
  }
  async shareSet(setId: number): Promise<ShareTokenOut> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/share`, { method: 'POST' });
  }
  async revokeSetShare(setId: number): Promise<void> {
    await this.transport.rawFetch(`/api/setbuilder/sets/${setId}/share`, { method: 'DELETE' });
  }
  async createCollaboratorInvite(
    setId: number,
    role: 'editor' | 'viewer'
  ): Promise<CollaboratorInviteCreated> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/collaborator-invites`, {
      method: 'POST',
      body: JSON.stringify({ role }),
    });
  }
  async listCollaboratorInvites(setId: number): Promise<CollaboratorInvite[]> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/collaborator-invites`);
  }
  async revokeCollaboratorInvite(setId: number, inviteId: number): Promise<void> {
    await this.transport.rawFetch(`/api/setbuilder/sets/${setId}/collaborator-invites/${inviteId}`, {
      method: 'DELETE',
    });
  }
  async acceptCollaboratorInvite(token: string): Promise<CollaboratorAccepted> {
    return this.transport.fetch(`/api/setbuilder/collaborator-invites/${encodeURIComponent(token)}/accept`, {
      method: 'POST',
    });
  }
  /** Public, unauthenticated read-only view of a shared set. */
  async getSharedSet(token: string): Promise<SharedSetView> {
    return this.transport.publicFetch(
      `${getApiUrl()}/api/public/setbuilder/shared/${encodeURIComponent(token)}`
    );
  }

  // WrzDJSet reusable set templates (issue #407)
  async saveSetAsTemplate(setId: number, name: string): Promise<SetTemplate> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/save-as-template`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }
  async listSetTemplates(): Promise<SetTemplateGalleryResponse> {
    return this.transport.fetch('/api/setbuilder/set-templates');
  }
  async instantiateSetTemplate(
    templateId: number,
    name?: string,
    eventId?: number
  ): Promise<SetDetail> {
    return this.transport.fetch(`/api/setbuilder/set-templates/${templateId}/instantiate`, {
      method: 'POST',
      body: JSON.stringify({ name: name ?? null, event_id: eventId ?? null }),
    });
  }
  async deleteSetTemplate(templateId: number): Promise<void> {
    await this.transport.rawFetch(`/api/setbuilder/set-templates/${templateId}`, { method: 'DELETE' });
  }

  // --- Setlist export (#396) ---

  async exportPreflight(setId: number, target: ExportTarget): Promise<ExportPreflight> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/export/preflight`, {
      method: 'POST',
      body: JSON.stringify({ target }),
    });
  }

  async exportSetToTidal(setId: number, skipUnresolved: boolean): Promise<ExportTidalResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/export/tidal`, {
      method: 'POST',
      body: JSON.stringify({ skip_unresolved: skipUnresolved }),
    });
  }

  async startSpotifyAuthorization(): Promise<{ authorization_url: string }> {
    return this.transport.fetch('/api/spotify/auth/start', {
      method: 'POST',
      credentials: 'include',
    });
  }

  async exportSetToSpotify(setId: number, skipUnresolved: boolean): Promise<ExportSpotifyResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/export/spotify`, {
      method: 'POST',
      body: JSON.stringify({ skip_unresolved: skipUnresolved }),
    });
  }

  async exportSetToAppleMusic(
    setId: number,
    skipUnresolved: boolean
  ): Promise<ExportAppleMusicResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/export/apple-music`, {
      method: 'POST',
      body: JSON.stringify({ skip_unresolved: skipUnresolved }),
    });
  }

  async reconcileAppleMusicExport(
    setId: number,
    request: ExportAppleMusicRecoveryRequest,
  ): Promise<ExportAppleMusicRecoveryResult> {
    return this.transport.fetch(`/api/setbuilder/sets/${setId}/export/apple-music/recovery`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  /**
   * Download a file export. Returns the blob plus the server-suggested
   * filename (falls back to `fallbackName` when Content-Disposition isn't
   * CORS-exposed).
   */
  async exportSetFile(
    setId: number,
    format: ExportFileFormat,
    skipUnresolved: boolean,
    fallbackName: string
  ): Promise<{ blob: Blob; filename: string }> {
    const res = await this.transport.rawFetch(`/api/setbuilder/sets/${setId}/export/file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format, skip_unresolved: skipUnresolved }),
    });
    const match = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '');
    return { blob: await res.blob(), filename: match?.[1] ?? fallbackName };
  }

}
