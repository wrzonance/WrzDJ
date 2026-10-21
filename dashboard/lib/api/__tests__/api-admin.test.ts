import { describe, it, expect, beforeEach } from 'vitest';
import { api } from '..';
import { mockFetch, setupApiClient } from './api-test-setup';

describe('ApiClient admin', () => {
  setupApiClient();
  describe('admin API', () => {
        beforeEach(() => {
        });

        it('fetches admin stats', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              total_users: 5,
              active_users: 4,
              pending_users: 1,
              total_events: 10,
              active_events: 3,
              total_requests: 50,
            }),
          });

          const stats = await api.getAdminStats();
          expect(stats.total_users).toBe(5);
          expect(stats.pending_users).toBe(1);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/stats');
        });

        it('fetches admin users with role filter', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              items: [{ id: 1, username: 'dj1', role: 'dj' }],
              total: 1,
              page: 1,
              limit: 20,
            }),
          });

          const result = await api.getAdminUsers(1, 20, 'dj');
          expect(result.items).toHaveLength(1);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('role=dj');
        });

        it('creates admin user', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 2, username: 'newdj', role: 'dj' }),
          });

          const user = await api.createAdminUser({
            username: 'newdj',
            password: 'password123',
            role: 'dj',
          });
          expect(user.username).toBe('newdj');

          const [, options] = mockFetch.mock.calls[0];
          expect(options.method).toBe('POST');
        });

        it('updates admin settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              registration_enabled: false,
              search_rate_limit_per_minute: 50,
            }),
          });

          const settings = await api.updateAdminSettings({
            registration_enabled: false,
          });
          expect(settings.registration_enabled).toBe(false);
        });
      });
  describe('AI Settings API', () => {
        beforeEach(() => {
        });

        it('fetches AI settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              llm_enabled: true,
              llm_rate_limit_per_minute: 3,
            }),
          });

          const result = await api.getAISettings();
          expect(result.llm_enabled).toBe(true);
          expect(result.llm_rate_limit_per_minute).toBe(3);
        });

        it('updates AI settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              llm_enabled: false,
              llm_rate_limit_per_minute: 5,
            }),
          });

          const result = await api.updateAISettings({
            llm_enabled: false,
            llm_rate_limit_per_minute: 5,
          });
          expect(result.llm_enabled).toBe(false);

          const [, options] = mockFetch.mock.calls[0];
          expect(options.method).toBe('PUT');
        });
      });
  describe('LLM Gateway API', () => {
        beforeEach(() => {
        });

        it('lists per-DJ connectors', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [
              {
                id: 1,
                user_id: 42,
                connector_type: 'openai_apikey',
                display_name: 'My OpenAI',
                status: 'active',
                base_url_plain: null,
                model_hint: 'gpt-5-mini',
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
                last_used_at: null,
                last_error: null,
              },
            ],
          });

          const result = await api.listLlmConnectors();
          expect(result).toHaveLength(1);
          expect(result[0].connector_type).toBe('openai_apikey');
        });

        it('creates a connector via POST', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 2,
              user_id: 42,
              connector_type: 'openai_compatible',
              display_name: 'Hermes',
              status: 'active',
              base_url_plain: 'http://127.0.0.1:11434/v1',
              model_hint: null,
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
              last_used_at: null,
              last_error: null,
            }),
          });

          const result = await api.createLlmConnector({
            connector_type: 'openai_compatible',
            display_name: 'Hermes',
            base_url: 'http://127.0.0.1:11434/v1',
            bearer: null,
            api_key: null,
            model_hint: null,
          });
          expect(result.id).toBe(2);

          const [, options] = mockFetch.mock.calls[0];
          expect(options.method).toBe('POST');
        });

        it('updates admin LLM policy via PATCH', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              llm_apikey_connectors_enabled: false,
              llm_compatible_connector_enabled: true,
              llm_default_connector_id: null,
            }),
          });
          const result = await api.updateAdminLlmPolicy({
            llm_apikey_connectors_enabled: false,
            llm_compatible_connector_enabled: null,
            llm_default_connector_id: null,
            clear_default: true,
          });
          expect(result.llm_apikey_connectors_enabled).toBe(false);

          const [, options] = mockFetch.mock.calls[0];
          expect(options.method).toBe('PATCH');
        });

        it('fetches admin usage with days param', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ days: 30, rows: [] }),
          });

          await api.getAdminLlmUsage(30);
          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/usage?days=30');
        });

        it('sets a connector monthly cap via PATCH', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 7, monthly_token_cap: 5000, current_month_tokens: 200 }),
          });

          const result = await api.setAdminLlmConnectorCap(7, 5000);
          expect(result.monthly_token_cap).toBe(5000);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/connectors/7/cap');
          expect(options.method).toBe('PATCH');
          expect(JSON.parse(options.body)).toEqual({ monthly_token_cap: 5000 });
        });

        it('clears a connector cap by passing null', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 7, monthly_token_cap: null, current_month_tokens: 0 }),
          });

          await api.setAdminLlmConnectorCap(7, null);
          const [, options] = mockFetch.mock.calls[0];
          expect(JSON.parse(options.body)).toEqual({ monthly_token_cap: null });
        });
      });
  describe('Org LLM connectors API', () => {
        beforeEach(() => {
        });

        it('lists org connectors', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [
              {
                id: 9,
                user_id: null,
                scope: 'org',
                connector_type: 'anthropic_apikey',
                display_name: 'House Anthropic',
                status: 'active',
                base_url_plain: null,
                model_hint: null,
                created_at: '2026-06-01T00:00:00Z',
                updated_at: '2026-06-01T00:00:00Z',
                last_used_at: null,
                last_error: null,
              },
            ],
          });

          const result = await api.listOrgConnectors();
          expect(result).toHaveLength(1);
          expect(result[0].scope).toBe('org');
          expect(result[0].user_id).toBeNull();

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/org-connectors');
        });

        it('creates an org connector via POST', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 10, scope: 'org', user_id: null }),
          });

          const result = await api.createOrgConnector({
            connector_type: 'anthropic_apikey',
            display_name: 'House Anthropic',
            base_url: null,
            bearer: null,
            api_key: 'sk-ant-test',
            model_hint: null,
          });
          expect(result.id).toBe(10);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/org-connectors');
          expect(options.method).toBe('POST');
        });

        it('tests an org connector via POST to the scoped URL', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ ok: true, message: 'pong' }),
          });

          await api.testOrgConnector(9);
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/org-connectors/9/test');
          expect(options.method).toBe('POST');
        });

        it('rotates org connector credentials via PUT', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 9, scope: 'org', user_id: null }),
          });

          await api.rotateOrgConnectorCredentials(9, {
            api_key: 'sk-ant-rotated',
            bearer: null,
          });
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/org-connectors/9/credentials');
          expect(options.method).toBe('PUT');
        });

        it('deletes an org connector via DELETE', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true, json: async () => null });

          await api.deleteOrgConnector(9);
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/org-connectors/9');
          expect(options.method).toBe('DELETE');
        });

        it('fetches per-DJ effective LLM status', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              rows: [
                { user_id: 42, username: 'dj42', effective_source: 'org_fallback' },
              ],
            }),
          });

          const result = await api.getDjLlmStatus();
          expect(result.rows).toHaveLength(1);
          expect(result.rows[0].effective_source).toBe('org_fallback');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/llm/dj-status');
        });
      });
  describe('Activity Log API', () => {
        beforeEach(() => {
        });

        it('fetches activity log', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [
              {
                id: 1,
                created_at: '2026-01-01T00:00:00Z',
                level: 'info',
                source: 'bridge',
                message: 'Bridge connected',
                event_code: 'ABC123',
              },
            ],
          });

          const result = await api.getActivityLog();
          expect(result).toHaveLength(1);
          expect(result[0].source).toBe('bridge');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/events/activity');
        });

        it('passes event_code filter', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => [],
          });

          await api.getActivityLog('ABC123');

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('event_code=ABC123');
        });
      });
  describe('admin users extended', () => {
        beforeEach(() => {
        });

        it('updates admin user role', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ id: 5, username: 'user5', role: 'admin' }),
          });

          const result = await api.updateAdminUser(5, { role: 'admin' });
          expect(result.role).toBe('admin');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/users/5');
          expect(options.method).toBe('PATCH');
        });

        it('deletes admin user', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 204,
            json: async () => undefined,
          });

          await api.deleteAdminUser(5);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/users/5');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('admin events', () => {
        beforeEach(() => {
        });

        it('fetches admin events with pagination', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              items: [{ code: 'E1', name: 'Event 1', owner_username: 'dj1' }],
              total: 1,
              page: 2,
              limit: 10,
            }),
          });

          const result = await api.getAdminEvents(2, 10);
          expect(result.items).toHaveLength(1);
          expect(result.page).toBe(2);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('page=2');
          expect(url).toContain('limit=10');
        });

        it('updates admin event', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ code: 'E1', name: 'Updated Name' }),
          });

          const result = await api.updateAdminEvent('E1', { name: 'Updated Name' });
          expect(result.name).toBe('Updated Name');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/events/E1');
          expect(options.method).toBe('PATCH');
        });

        it('deletes admin event', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            status: 204,
            json: async () => undefined,
          });

          await api.deleteAdminEvent('E1');

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/events/E1');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('admin settings (GET)', () => {
        it('fetches admin settings', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              registration_enabled: true,
              search_rate_limit_per_minute: 30,
              spotify_enabled: true,
              tidal_enabled: false,
            }),
          });

          const result = await api.getAdminSettings();
          expect(result.registration_enabled).toBe(true);
          expect(result.search_rate_limit_per_minute).toBe(30);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/settings');
        });
      });
  describe('admin integrations', () => {
        beforeEach(() => {
        });

        it('fetches all integration statuses', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              services: [
                { service: 'spotify', enabled: true, healthy: true },
                { service: 'tidal', enabled: false, healthy: false },
              ],
            }),
          });

          const result = await api.getIntegrations();
          expect(result.services).toHaveLength(2);

          const [url] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/integrations');
        });

        it('toggles integration on/off', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ service: 'spotify', enabled: false }),
          });

          const result = await api.toggleIntegration('spotify', false);
          expect(result.enabled).toBe(false);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/integrations/spotify');
          expect(options.method).toBe('PATCH');
          expect(JSON.parse(options.body)).toEqual({ enabled: false });
        });

        it('checks integration health', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              service: 'spotify',
              healthy: true,
              message: 'All checks passed',
            }),
          });

          const result = await api.checkIntegrationHealth('spotify');
          expect(result.healthy).toBe(true);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/admin/integrations/spotify/check');
          expect(options.method).toBe('POST');
        });
      });
});
