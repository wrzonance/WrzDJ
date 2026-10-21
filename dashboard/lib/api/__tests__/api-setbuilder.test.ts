import { describe, it, expect } from 'vitest';
import { api, ApiError } from '..';
import { mockFetch, setupApiClient } from './api-test-setup';

describe('ApiClient setbuilder', () => {
  setupApiClient();
  describe('setbuilder two-pass API', () => {
        it('runs deterministic build with explicit confirmation', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ slot_count: 2, iterations: 1, slots: [], transition_scores: [] }),
          });

          const result = await api.buildSet(42, true);

          expect(result.slot_count).toBe(2);
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/setbuilder/sets/42/build');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ confirmed: true });
        });

        it('requests structured critique', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ overall_grade: 'B+', summary: 'Good arc', flags: [] }),
          });

          const critique = await api.critiqueSet(42);

          expect(critique.overall_grade).toBe('B+');
          expect(mockFetch.mock.calls[0][0]).toContain('/api/setbuilder/sets/42/critique');
        });

        it('records an Apple Music playlist found during export recovery', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ status: 'exported' }),
          });

          const result = await api.reconcileAppleMusicExport(42, {
            action: 'playlist_found',
            playlist_id: 'p.savedPlaylist',
          });

          expect(result.status).toBe('exported');
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/setbuilder/sets/42/export/apple-music/recovery');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({
            action: 'playlist_found',
            playlist_id: 'p.savedPlaylist',
          });
        });

        it('loads agent history and sends chat turns without client history', async () => {
          mockFetch
            .mockResolvedValueOnce({
              ok: true,
              json: async () => ({
                messages: [],
                context_summary: null,
                compacted_through_message_id: null,
                uses_compact_context: true,
                recent_turn_limit: 12,
              }),
            })
            .mockResolvedValueOnce({
              ok: true,
              json: async () => ({
                message: 'Swapped slot 1 Track A with slot 2 Track B.',
                assistant_message: {
                  id: 2,
                  role: 'assistant',
                  content: 'Swapped slot 1 Track A with slot 2 Track B.',
                  display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
                  tool_calls: [],
                  affected_transition_scores: [],
                  created_at: '2026-06-15T00:00:00Z',
                },
                tool_calls: [],
                slots: [],
                affected_transition_scores: [],
              }),
            });

          const history = await api.getSetAgentHistory(42);
          const chat = await api.chatWithSetAgent(42, { message: 'Swap these' });

          expect(history.uses_compact_context).toBe(true);
          expect(chat.message).toContain('Swapped slot 1');
          const [historyUrl] = mockFetch.mock.calls[0];
          expect(historyUrl).toContain('/api/setbuilder/sets/42/agent/history');
          const [chatUrl, chatOptions] = mockFetch.mock.calls[1];
          expect(chatUrl).toContain('/api/setbuilder/sets/42/agent/chat');
          expect(JSON.parse(chatOptions.body)).toEqual({ message: 'Swap these' });
        });

        it('loads and resets the SetBuilder taste profile', async () => {
          mockFetch
            .mockResolvedValueOnce({
              ok: true,
              json: async () => ({
                sample_count: 5,
                min_samples: 5,
                active: true,
                average_energy_delta: 2,
                energy_adjustment: 1.5,
                top_moods: [{ mood: 'Peak', count: 4 }],
                summary: 'Learned from 5 edits: energy +1.5; top mood Peak.',
                reset_at: null,
              }),
            })
            .mockResolvedValueOnce({
              ok: true,
              json: async () => ({
                sample_count: 0,
                min_samples: 5,
                active: false,
                average_energy_delta: null,
                energy_adjustment: 0,
                top_moods: [],
                summary: 'No learned taste profile yet.',
                reset_at: '2026-06-26T18:00:00Z',
              }),
            });

          const profile = await api.getSetbuilderTasteProfile();
          const reset = await api.resetSetbuilderTasteProfile();

          expect(profile.active).toBe(true);
          expect(reset.sample_count).toBe(0);
          const [getUrl] = mockFetch.mock.calls[0];
          expect(getUrl).toContain('/api/setbuilder/taste-profile');
          const [resetUrl, resetOptions] = mockFetch.mock.calls[1];
          expect(resetUrl).toContain('/api/setbuilder/taste-profile/reset');
          expect(resetOptions.method).toBe('POST');
        });
      });
  describe('setbuilder templates API (issue #407)', () => {
        it('saveSetAsTemplate POSTs the name to save-as-template', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 7,
              name: 'Peak Hour Arc',
              vibe_theme: null,
              target_duration_sec: 3600,
              avg_transition_overlap_sec: 8,
              bpm_floor: null,
              bpm_ceiling: null,
              key_strictness: 0.2,
              slot_count: 12,
              curve_points: [],
              created_at: '2026-07-27T00:00:00Z',
              updated_at: '2026-07-27T00:00:00Z',
            }),
          });

          const tpl = await api.saveSetAsTemplate(42, 'Peak Hour Arc');

          expect(tpl.id).toBe(7);
          expect(tpl.slot_count).toBe(12);
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/setbuilder/sets/42/save-as-template');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ name: 'Peak Hour Arc' });
        });

        it('listSetTemplates GETs the gallery and returns it even when empty', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ templates: [] }),
          });

          const result = await api.listSetTemplates();

          expect(result.templates).toEqual([]);
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/setbuilder/set-templates');
          expect(options.method).toBeUndefined();
        });

        it('instantiateSetTemplate POSTs optional name + event_id', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 99,
              name: 'Peak Hour Arc',
              event_id: 5,
              status: 'draft',
              sharing_mode: 'private',
              share_token: null,
              created_at: '2026-07-27T00:00:00Z',
              updated_at: '2026-07-27T00:00:00Z',
              vibe_theme: null,
              target_duration_sec: 3600,
              avg_transition_overlap_sec: 8,
              bpm_floor: null,
              bpm_ceiling: null,
              key_strictness: 0.2,
              tidal_playlist_id: null,
              exported_at: null,
            }),
          });

          const newSet = await api.instantiateSetTemplate(7, 'Friday Night', 5);

          expect(newSet.id).toBe(99);
          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/setbuilder/set-templates/7/instantiate');
          expect(options.method).toBe('POST');
          expect(JSON.parse(options.body)).toEqual({ name: 'Friday Night', event_id: 5 });
        });

        it('instantiateSetTemplate omits name/event_id as null when not passed', async () => {
          mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({
              id: 100,
              name: 'Peak Hour Arc',
              event_id: null,
              status: 'draft',
              sharing_mode: 'private',
              share_token: null,
              created_at: '2026-07-27T00:00:00Z',
              updated_at: '2026-07-27T00:00:00Z',
              vibe_theme: null,
              target_duration_sec: null,
              avg_transition_overlap_sec: 8,
              bpm_floor: null,
              bpm_ceiling: null,
              key_strictness: 0.2,
              tidal_playlist_id: null,
              exported_at: null,
            }),
          });

          await api.instantiateSetTemplate(7);

          const [, options] = mockFetch.mock.calls[0];
          expect(JSON.parse(options.body)).toEqual({ name: null, event_id: null });
        });

        it('deleteSetTemplate sends DELETE with no body', async () => {
          mockFetch.mockResolvedValueOnce({ ok: true });

          await api.deleteSetTemplate(7);

          const [url, options] = mockFetch.mock.calls[0];
          expect(url).toContain('/api/setbuilder/set-templates/7');
          expect(options.method).toBe('DELETE');
        });
      });
  describe('Apple Music set export', () => {
        it('preserves the uncertain write code, message, and known playlist ID from HTTP errors', async () => {
          const detail = {
            code: 'apple_music_write_uncertain',
            message: 'Do not retry; check your library.',
            playlist_id: 'p.playlist123',
          };
          mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ detail }), { status: 502 }));

          const error = await api.exportSetToAppleMusic(42, false).catch((caught: unknown) => caught);

          expect(error).toBeInstanceOf(ApiError);
          expect(error).toMatchObject({
            status: 502,
            message: detail.message,
            code: detail.code,
            detail,
          });
          expect(mockFetch).toHaveBeenCalledWith(
            expect.stringContaining('/api/setbuilder/sets/42/export/apple-music'),
            expect.objectContaining({ method: 'POST' }),
          );
        });
      });
});
