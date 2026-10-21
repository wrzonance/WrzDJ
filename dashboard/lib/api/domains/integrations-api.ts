import type { ApiTransport } from '../transport';

import type { BeatportEventSettings, BeatportSearchResult, BeatportStatus, AppleMusicStatus, AppleMusicDeveloperToken, Event, LLMRecommendationResponse, PlaylistListResponse, RecommendationResponse, TidalEventSettings, TidalSearchResult, TidalSyncResult, TidalStatus } from '../types';

export class IntegrationsApi {
  constructor(public readonly transport: ApiTransport) {}

  async getAppleMusicStatus(): Promise<AppleMusicStatus> {
    return this.transport.fetch('/api/apple-music/status');
  }

  async getAppleMusicDeveloperToken(): Promise<AppleMusicDeveloperToken> {
    return this.transport.fetch('/api/apple-music/developer-token');
  }

  async linkAppleMusicAccount(musicUserToken: string): Promise<AppleMusicStatus> {
    return this.transport.fetch('/api/apple-music/link', {
      method: 'POST',
      body: JSON.stringify({ music_user_token: musicUserToken }),
    });
  }

  async disconnectAppleMusicAccount(): Promise<void> {
    await this.transport.fetch('/api/apple-music/disconnect', { method: 'POST' });
  }

  /**
   * Get Tidal account status for current user.
   */
  async getTidalStatus(): Promise<TidalStatus> {
    return this.transport.fetch('/api/tidal/status');
  }

  /**
   * Start Tidal device login flow.
   * Returns URL and code for user to visit.
   */
  async startTidalAuth(): Promise<{ verification_url: string; user_code: string; message: string }> {
    return this.transport.fetch('/api/tidal/auth/start', { method: 'POST' });
  }

  /**
   * Check if Tidal device login is complete.
   */
  async checkTidalAuth(): Promise<{ complete: boolean; pending?: boolean; error?: string; verification_url?: string; user_code?: string; user_id?: string }> {
    return this.transport.fetch('/api/tidal/auth/check');
  }

  /**
   * Cancel pending Tidal device login.
   */
  async cancelTidalAuth(): Promise<{ status: string; message: string }> {
    return this.transport.fetch('/api/tidal/auth/cancel', { method: 'POST' });
  }

  /**
   * Disconnect Tidal account.
   */
  async disconnectTidal(): Promise<{ status: string; message: string }> {
    return this.transport.fetch('/api/tidal/disconnect', { method: 'POST' });
  }

  /**
   * Get Tidal sync settings for an event.
   */
  async getTidalEventSettings(eventId: number): Promise<TidalEventSettings> {
    return this.transport.fetch(`/api/tidal/events/${eventId}/settings`);
  }

  /**
   * Update Tidal sync settings for an event.
   */
  async updateTidalEventSettings(
    eventId: number,
    settings: { tidal_sync_enabled: boolean }
  ): Promise<TidalEventSettings> {
    return this.transport.fetch(`/api/tidal/events/${eventId}/settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  }

  /**
   * Search Tidal for tracks (for manual linking).
   */
  async searchTidal(query: string, limit: number = 10): Promise<TidalSearchResult[]> {
    return this.transport.fetch(`/api/tidal/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }

  /**
   * Manually sync a request to Tidal.
   */
  async syncRequestToTidal(requestId: number): Promise<TidalSyncResult> {
    return this.transport.fetch(`/api/tidal/requests/${requestId}/sync`, { method: 'POST' });
  }

  /**
   * Manually link a Tidal track to a request.
   */
  async linkTidalTrack(requestId: number, tidalTrackId: string): Promise<TidalSyncResult> {
    return this.transport.fetch(`/api/tidal/requests/${requestId}/link`, {
      method: 'POST',
      body: JSON.stringify({ tidal_track_id: tidalTrackId }),
    });
  }
  // ========== Beatport Integration ==========

  async getBeatportStatus(): Promise<BeatportStatus> {
    return this.transport.fetch('/api/beatport/status');
  }

  async loginBeatport(username: string, password: string): Promise<{ status: string; message: string }> {
    return this.transport.fetch('/api/beatport/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  }

  async disconnectBeatport(): Promise<{ status: string; message: string }> {
    return this.transport.fetch('/api/beatport/disconnect', { method: 'POST' });
  }

  async getBeatportEventSettings(eventId: number): Promise<BeatportEventSettings> {
    return this.transport.fetch(`/api/beatport/events/${eventId}/settings`);
  }

  async updateBeatportEventSettings(
    eventId: number,
    settings: { beatport_sync_enabled: boolean }
  ): Promise<BeatportEventSettings> {
    return this.transport.fetch(`/api/beatport/events/${eventId}/settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  }

  async searchBeatport(query: string, limit: number = 10): Promise<BeatportSearchResult[]> {
    return this.transport.fetch(`/api/beatport/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }

  async linkBeatportTrack(requestId: number, beatportTrackId: string): Promise<{ status: string }> {
    return this.transport.fetch(`/api/beatport/requests/${requestId}/link`, {
      method: 'POST',
      body: JSON.stringify({ beatport_track_id: beatportTrackId }),
    });
  }

  // ========== Recommendations ==========

  async generateRecommendations(code: string): Promise<RecommendationResponse> {
    return this.transport.fetch(`/api/events/${code}/recommendations`, {
      method: 'POST',
    });
  }

  async getEventPlaylists(code: string): Promise<PlaylistListResponse> {
    return this.transport.fetch(`/api/events/${code}/playlists`);
  }

  async generateLLMRecommendations(code: string, prompt: string): Promise<LLMRecommendationResponse> {
    return this.transport.fetch(`/api/events/${code}/recommendations/llm`, {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  }

  async generateRecommendationsFromTemplate(
    code: string, source: string, playlistId: string
  ): Promise<RecommendationResponse> {
    return this.transport.fetch(`/api/events/${code}/recommendations/from-template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, playlist_id: playlistId }),
    });
  }

  // ========== Banner ==========

  async uploadEventBanner(code: string, file: File): Promise<Event> {
    const formData = new FormData();
    formData.append('file', file);
    // Do NOT set Content-Type — browser sets it with multipart boundary
    const response = await this.transport.rawFetch(`/api/events/${code}/banner`, {
      method: 'POST',
      body: formData,
    });
    return response.json();
  }

  async deleteEventBanner(code: string): Promise<Event> {
    return this.transport.fetch(`/api/events/${code}/banner`, { method: 'DELETE' });
  }

  // ========== Admin ==========

}
