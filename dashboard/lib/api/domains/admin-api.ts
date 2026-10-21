import type { ApiTransport } from '../transport';
import type {
  AdminEvent,
  AdminGuest,
  AdminGuestFilter,
  AdminGuestProfileUpdate,
  AdminGuestUpdate,
} from '../types';
import type { UserRole } from '../../auth';
import type { LlmStreamChunk, AdminLlmAuditFilters } from '../contracts';
import { ApiError, CSRF_HEADER_NAME, CSRF_HEADER_VALUE, getApiUrl } from '../shared';
import type { AdminUser, AIModelsResponse, AISettings, AISettingsUpdate, LlmAdminAudit, LlmAdminConnector, LlmAdminPolicy, LlmAdminPolicyPatch, LlmAdminUsage, LlmConnector, LlmConnectorCreate, LlmConnectorCredentialsRotate, LlmConnectorPatch, LlmConnectorTestResult, LlmDjPolicy, LlmDjStatus, LlmFeatureKey, LlmFeaturePreferences, LlmFeaturePreferenceSet, IntegrationCheckResponse, IntegrationHealthResponse, IntegrationToggleResponse, PaginatedResponse, SystemSettings, SystemStats } from '../types';


const LLM_STREAM_STOP_REASONS = new Set(['end_turn', 'tool_use', 'max_tokens', 'error']);
const LLM_STREAM_FIELDS = new Set(['text_delta', 'tool_call_deltas', 'stop_reason', 'usage', 'done']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isLlmStreamChunk(value: unknown): value is LlmStreamChunk {
  if (!isRecord(value)) return false;
  const fields = Object.keys(value);
  if (fields.length === 0 || fields.some((field) => !LLM_STREAM_FIELDS.has(field))) return false;
  if ('text_delta' in value && typeof value.text_delta !== 'string') return false;
  if ('done' in value && typeof value.done !== 'boolean') return false;
  if (
    'stop_reason' in value && value.stop_reason !== null &&
    (typeof value.stop_reason !== 'string' || !LLM_STREAM_STOP_REASONS.has(value.stop_reason))
  ) return false;
  if ('usage' in value && value.usage !== null) {
    if (
      !isRecord(value.usage) ||
      Object.keys(value.usage).some((field) => field !== 'prompt' && field !== 'completion') ||
      typeof value.usage.prompt !== 'number' || !Number.isFinite(value.usage.prompt) ||
      typeof value.usage.completion !== 'number' || !Number.isFinite(value.usage.completion)
    ) {
      return false;
    }
  }
  if ('tool_call_deltas' in value) {
    if (!Array.isArray(value.tool_call_deltas) || !value.tool_call_deltas.every(isToolCallDelta)) return false;
  }
  return true;
}

function isToolCallDelta(value: unknown): boolean {
  if (
    !isRecord(value) ||
    Object.keys(value).some((field) => !['index', 'id', 'name', 'input_json_fragment'].includes(field)) ||
    typeof value.index !== 'number' || !Number.isInteger(value.index) || value.index < 0
  ) return false;
  return (
    (!('id' in value) || value.id === null || typeof value.id === 'string') &&
    (!('name' in value) || value.name === null || typeof value.name === 'string') &&
    (!('input_json_fragment' in value) || typeof value.input_json_fragment === 'string')
  );
}

export class AdminApi {
  constructor(public readonly transport: ApiTransport) {}

  async getAdminStats(): Promise<SystemStats> {
    return this.transport.fetch('/api/admin/stats');
  }

  async getAdminUsers(
    page: number = 1,
    limit: number = 20,
    role?: UserRole
  ): Promise<PaginatedResponse<AdminUser>> {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (role) params.set('role', role);
    return this.transport.fetch(`/api/admin/users?${params}`);
  }

  async createAdminUser(data: {
    username: string;
    password: string;
    role: UserRole;
  }): Promise<AdminUser> {
    return this.transport.fetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateAdminUser(
    userId: number,
    data: { role?: UserRole; is_active?: boolean; password?: string }
  ): Promise<AdminUser> {
    return this.transport.fetch(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteAdminUser(userId: number): Promise<void> {
    await this.transport.rawFetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
  }

  async getAdminEvents(
    page: number = 1,
    limit: number = 20
  ): Promise<PaginatedResponse<AdminEvent>> {
    return this.transport.fetch(`/api/admin/events?page=${page}&limit=${limit}`);
  }

  async updateAdminEvent(
    code: string,
    data: { name?: string; expires_at?: string }
  ): Promise<AdminEvent> {
    return this.transport.fetch(`/api/admin/events/${code}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteAdminEvent(code: string): Promise<void> {
    await this.transport.rawFetch(`/api/admin/events/${code}`, { method: 'DELETE' });
  }

  async bulkDeleteAdminEvents(codes: string[]): Promise<{ status: string; count: number }> {
    return this.transport.fetch('/api/admin/events/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ codes }),
    });
  }

  // ========== Admin guests (#862) ==========

  async getAdminGuests(
    page: number = 1,
    limit: number = 20,
    filter: AdminGuestFilter = 'all',
    q?: string
  ): Promise<PaginatedResponse<AdminGuest>> {
    const params = new URLSearchParams({ page: String(page), limit: String(limit), filter });
    if (q) params.set('q', q);
    return this.transport.fetch(`/api/admin/guests?${params}`);
  }

  async updateAdminGuest(guestId: number, data: AdminGuestUpdate): Promise<AdminGuest> {
    return this.transport.fetch(`/api/admin/guests/${guestId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async updateAdminGuestProfile(
    guestId: number,
    eventId: number,
    data: AdminGuestProfileUpdate
  ): Promise<AdminGuest> {
    return this.transport.fetch(`/api/admin/guests/${guestId}/events/${eventId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteAdminGuest(guestId: number): Promise<void> {
    await this.transport.rawFetch(`/api/admin/guests/${guestId}`, { method: 'DELETE' });
  }

  async getAdminSettings(): Promise<SystemSettings> {
    return this.transport.fetch('/api/admin/settings');
  }

  async updateAdminSettings(data: Partial<SystemSettings>): Promise<SystemSettings> {
    return this.transport.fetch('/api/admin/settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // ========== Admin Integrations ==========

  async getIntegrations(): Promise<IntegrationHealthResponse> {
    return this.transport.fetch('/api/admin/integrations');
  }

  async toggleIntegration(
    service: string,
    enabled: boolean
  ): Promise<IntegrationToggleResponse> {
    return this.transport.fetch(`/api/admin/integrations/${service}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    });
  }

  async checkIntegrationHealth(
    service: string
  ): Promise<IntegrationCheckResponse> {
    return this.transport.fetch(`/api/admin/integrations/${service}/check`, {
      method: 'POST',
    });
  }

  // ========== Admin AI Settings ==========

  async getAISettings(): Promise<AISettings> {
    return this.transport.fetch('/api/admin/ai/settings');
  }

  async updateAISettings(data: AISettingsUpdate): Promise<AISettings> {
    return this.transport.fetch('/api/admin/ai/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  // ========== LLM connectors (per-DJ) ==========

  async listLlmConnectors(): Promise<LlmConnector[]> {
    return this.transport.fetch('/api/llm/connectors');
  }

  // DJ-readable connector policy (non-sensitive subset). The settings/ai page
  // uses this to fail closed — hiding connector types the admin disabled —
  // instead of falling back to "all types allowed" on the admin-only endpoint.
  async getLlmPolicy(): Promise<LlmDjPolicy> {
    return this.transport.fetch('/api/llm/policy');
  }

  async listOpenRouterModels(): Promise<AIModelsResponse> {
    return this.transport.fetch('/api/llm/openrouter/models');
  }

  async createLlmConnector(data: LlmConnectorCreate): Promise<LlmConnector> {
    return this.transport.fetch('/api/llm/connectors', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateLlmConnector(id: number, data: LlmConnectorPatch): Promise<LlmConnector> {
    return this.transport.fetch(`/api/llm/connectors/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async rotateLlmConnectorCredentials(
    id: number,
    data: LlmConnectorCredentialsRotate,
  ): Promise<LlmConnector> {
    return this.transport.fetch(`/api/llm/connectors/${id}/credentials`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async testLlmConnector(id: number): Promise<LlmConnectorTestResult> {
    return this.transport.fetch(`/api/llm/connectors/${id}/test`, { method: 'POST' });
  }

  /**
   * Stream a short health-check sentence through a connector via SSE.
   *
   * Uses fetch + ReadableStream rather than EventSource so the authenticated
   * request can include the dashboard session cookie and CSRF header.
   * Pass an AbortSignal to cancel — aborting closes the connection, which the
   * backend treats as a client disconnect and cancels the upstream provider
   * request. `onChunk` is invoked for every parsed SSE data frame.
   */
  async streamConnectorTest(
    id: number,
    onChunk: (chunk: LlmStreamChunk) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const headers = new Headers({ Accept: 'text/event-stream' });
    headers.set(CSRF_HEADER_NAME, CSRF_HEADER_VALUE);

    const response = await fetch(`${getApiUrl()}/api/llm/connectors/${id}/stream-test`, {
      method: 'POST',
      headers,
      signal,
      credentials: 'include',
    });
    if (!response.ok || !response.body) {
      if (response.status === 401 && this.transport.onUnauthorized) this.transport.onUnauthorized();
      throw new ApiError('Stream test failed', response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    // SSE frames are separated by a blank line. The spec allows LF (`\n\n`) or
    // CRLF (`\r\n\r\n`) terminators, so match either — a CRLF-emitting server or
    // proxy must not leave frames (including `event: error`) unparsed.
    const frameBoundary = /\r?\n\r?\n/;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.search(frameBoundary)) !== -1) {
          const frame = buffer.slice(0, sep);
          const boundary = buffer.slice(sep).match(frameBoundary)?.[0] ?? '\n\n';
          buffer = buffer.slice(sep + boundary.length);
          // A frame may carry an `event:` name plus one or more `data:` lines.
          // The backend emits `event: error` for typed gateway failures, so we
          // must inspect the event type — not just blindly parse `data:`.
          let eventType = 'message';
          const dataLines: string[] = [];
          for (const line of frame.split(/\r?\n/)) {
            if (line.startsWith('event:')) {
              eventType = line.slice('event:'.length).trim();
            } else if (line.startsWith('data:')) {
              dataLines.push(line.slice('data:'.length).trim());
            }
          }
          const data = dataLines.join('\n').trim();
          if (!data || data === '[DONE]') continue;

          if (eventType === 'error') {
            // Surface the sanitised backend error code as a thrown failure
            // rather than passing it through as an inert chunk.
            let code: string | undefined;
            try {
              code = (JSON.parse(data) as { code?: string }).code;
            } catch {
              code = undefined;
            }
            throw new ApiError(`Stream test failed${code ? `: ${code}` : ''}`, 500);
          }

          let payload: unknown;
          try {
            payload = JSON.parse(data);
          } catch {
            // Ignore unparseable keepalive frames.
            continue;
          }
          if (!isLlmStreamChunk(payload)) continue;
          onChunk(payload);
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  async deleteLlmConnector(id: number): Promise<void> {
    await this.transport.rawFetch(`/api/llm/connectors/${id}`, { method: 'DELETE' });
  }

  // Pin / unpin a connector as the DJ's explicit default (issue #336). When
  // pinned, the gateway routes through this connector regardless of which one
  // is most-recently-used.
  async setLlmConnectorDefault(id: number): Promise<LlmConnector> {
    return this.transport.fetch(`/api/llm/connectors/${id}/default`, { method: 'POST' });
  }

  async unsetLlmConnectorDefault(id: number): Promise<LlmConnector> {
    return this.transport.fetch(`/api/llm/connectors/${id}/default`, { method: 'DELETE' });
  }

  // ========== Per-feature connector preferences (issue #337) ==========

  async listLlmFeaturePreferences(): Promise<LlmFeaturePreferences> {
    return this.transport.fetch('/api/llm/feature-preferences');
  }

  async setLlmFeaturePreference(data: LlmFeaturePreferenceSet): Promise<LlmFeaturePreferences> {
    return this.transport.fetch('/api/llm/feature-preferences', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async clearLlmFeaturePreference(feature: LlmFeatureKey): Promise<LlmFeaturePreferences> {
    return this.transport.fetch(`/api/llm/feature-preferences/${feature}`, {
      method: 'DELETE',
    });
  }

  // ========== Admin LLM policy + oversight ==========

  async getAdminLlmPolicy(): Promise<LlmAdminPolicy> {
    return this.transport.fetch('/api/admin/llm/policy');
  }

  async updateAdminLlmPolicy(data: LlmAdminPolicyPatch): Promise<LlmAdminPolicy> {
    return this.transport.fetch('/api/admin/llm/policy', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async listAllLlmConnectors(): Promise<LlmAdminConnector[]> {
    return this.transport.fetch('/api/admin/llm/connectors');
  }

  async revokeAdminLlmConnector(id: number): Promise<LlmAdminConnector> {
    return this.transport.fetch(`/api/admin/llm/connectors/${id}/revoke`, { method: 'POST' });
  }

  async getAdminLlmUsage(days = 30): Promise<LlmAdminUsage> {
    return this.transport.fetch(`/api/admin/llm/usage?days=${days}`);
  }

  /**
   * Set or clear a connector's monthly token cap (admin-only, issue #339).
   * Pass `null` to clear the cap (unlimited).
   */
  async setAdminLlmConnectorCap(
    id: number,
    monthlyTokenCap: number | null,
  ): Promise<LlmAdminConnector> {
    return this.transport.fetch(`/api/admin/llm/connectors/${id}/cap`, {
      method: 'PATCH',
      body: JSON.stringify({ monthly_token_cap: monthlyTokenCap }),
    });
  }

  // ========== Admin org-scoped house connector ==========

  async listOrgConnectors(): Promise<LlmConnector[]> {
    return this.transport.fetch('/api/admin/llm/org-connectors');
  }

  async createOrgConnector(data: LlmConnectorCreate): Promise<LlmConnector> {
    return this.transport.fetch('/api/admin/llm/org-connectors', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async testOrgConnector(id: number): Promise<LlmConnectorTestResult> {
    return this.transport.fetch(`/api/admin/llm/org-connectors/${id}/test`, { method: 'POST' });
  }

  async rotateOrgConnectorCredentials(
    id: number,
    data: LlmConnectorCredentialsRotate,
  ): Promise<LlmConnector> {
    return this.transport.fetch(`/api/admin/llm/org-connectors/${id}/credentials`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteOrgConnector(id: number): Promise<void> {
    await this.transport.rawFetch(`/api/admin/llm/org-connectors/${id}`, { method: 'DELETE' });
  }

  // Effective LLM credential source per DJ (own / org_fallback / none) —
  // backend-computed by the same rules the gateway resolver applies, so the
  // admin UI never duplicates resolution logic.
  async getDjLlmStatus(): Promise<LlmDjStatus> {
    return this.transport.fetch('/api/admin/llm/dj-status');
  }

  // ========== Admin LLM audit trail (issue #341) ==========

  private buildAuditQuery(filters: AdminLlmAuditFilters = {}): URLSearchParams {
    const params = new URLSearchParams();
    if (filters.event_type) params.set('event_type', filters.event_type);
    if (filters.actor_user_id != null) {
      params.set('actor_user_id', String(filters.actor_user_id));
    }
    if (filters.target_connector_id != null) {
      params.set('target_connector_id', String(filters.target_connector_id));
    }
    if (filters.days != null) params.set('days', String(filters.days));
    if (filters.limit != null) params.set('limit', String(filters.limit));
    if (filters.offset != null) params.set('offset', String(filters.offset));
    return params;
  }

  async getAdminLlmAudit(filters: AdminLlmAuditFilters = {}): Promise<LlmAdminAudit> {
    const params = this.buildAuditQuery(filters);
    return this.transport.fetch(`/api/admin/llm/audit?${params.toString()}`);
  }

  /**
   * Download the (filtered) audit trail as a CSV Blob. Pagination params are
   * ignored server-side for the export — it honors only the filter fields.
   */
  async downloadAdminLlmAuditCsv(filters: AdminLlmAuditFilters = {}): Promise<Blob> {
    const params = this.buildAuditQuery({
      event_type: filters.event_type,
      actor_user_id: filters.actor_user_id,
      target_connector_id: filters.target_connector_id,
      days: filters.days,
    });
    const response = await this.transport.rawFetch(`/api/admin/llm/audit.csv?${params.toString()}`);
    return response.blob();
  }

  // ========== Kiosk Pairing ==========

}
