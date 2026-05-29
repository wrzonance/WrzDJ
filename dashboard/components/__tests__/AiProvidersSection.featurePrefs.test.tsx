import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import AiProvidersSection from '../AiProvidersSection';
import { api } from '@/lib/api';
import type { LlmConnector } from '@/lib/api-types';

const NOW = new Date().toISOString();

function makeConnector(overrides: Partial<LlmConnector> = {}): LlmConnector {
  return {
    id: 1,
    user_id: 42,
    connector_type: 'openai_apikey',
    display_name: 'My OpenAI',
    status: 'active',
    base_url_plain: null,
    model_hint: null,
    created_at: NOW,
    updated_at: NOW,
    last_used_at: null,
    last_error: null,
    is_default: false,
    last_health_check_at: null,
    last_health_check_status: null,
    monthly_token_cap: null,
    ...overrides,
  };
}

describe('AiProvidersSection per-feature defaults', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([makeConnector()]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: true,
      llm_compatible_connector_enabled: true,
      allowed_connector_types: ['openai_apikey'],
    });
    vi.spyOn(api, 'listLlmFeaturePreferences').mockResolvedValue({
      preferences: [],
      known_features: ['recommendation', 'set_builder'],
    });
  });

  it('renders a picker per known feature and sets a pin', async () => {
    const setSpy = vi.spyOn(api, 'setLlmFeaturePreference').mockResolvedValue({
      preferences: [{ feature: 'recommendation', connector_id: 1 }],
      known_features: ['recommendation', 'set_builder'],
    });

    render(<AiProvidersSection />);

    await waitFor(() =>
      expect(screen.getByText('Per-feature defaults')).toBeInTheDocument(),
    );

    // One picker per known feature.
    expect(screen.getByLabelText('Recommendations')).toBeInTheDocument();
    expect(screen.getByLabelText('Set builder')).toBeInTheDocument();

    const select = screen.getByLabelText('Recommendations') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '1' } });

    await waitFor(() =>
      expect(setSpy).toHaveBeenCalledWith({
        feature: 'recommendation',
        connector_id: 1,
      }),
    );
  });

  it('clears a pin when "Use account default" is selected', async () => {
    vi.spyOn(api, 'listLlmFeaturePreferences').mockResolvedValue({
      preferences: [{ feature: 'recommendation', connector_id: 1 }],
      known_features: ['recommendation', 'set_builder'],
    });
    const clearSpy = vi.spyOn(api, 'clearLlmFeaturePreference').mockResolvedValue({
      preferences: [],
      known_features: ['recommendation', 'set_builder'],
    });

    render(<AiProvidersSection />);
    await waitFor(() =>
      expect(screen.getByText('Per-feature defaults')).toBeInTheDocument(),
    );

    const select = screen.getByLabelText('Recommendations') as HTMLSelectElement;
    // The current pin should be reflected as the selected value.
    expect(select.value).toBe('1');

    fireEvent.change(select, { target: { value: '' } });

    await waitFor(() => expect(clearSpy).toHaveBeenCalledWith('recommendation'));
  });

  it('hides the section when the preferences fetch fails (fail soft)', async () => {
    vi.spyOn(api, 'listLlmFeaturePreferences').mockRejectedValue(new Error('boom'));

    render(<AiProvidersSection />);

    // The connectors list still renders…
    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    // …but the per-feature section is absent.
    expect(screen.queryByText('Per-feature defaults')).not.toBeInTheDocument();
  });

  it('only offers active connectors in the picker', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({ id: 1, display_name: 'Active one', status: 'active' }),
      makeConnector({ id: 2, display_name: 'Broken one', status: 'auth_invalid' }),
    ]);

    render(<AiProvidersSection />);
    await waitFor(() =>
      expect(screen.getByText('Per-feature defaults')).toBeInTheDocument(),
    );

    const select = screen.getByLabelText('Recommendations') as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    expect(optionLabels).toContain('Active one');
    expect(optionLabels).not.toContain('Broken one');
  });
});
