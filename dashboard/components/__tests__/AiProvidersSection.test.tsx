import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import AiProvidersSection from '../AiProvidersSection';
import { api } from '@/lib/api';
import type { LlmConnector, LlmConnectorType, LlmDjPolicy } from '@/lib/api-types';

const ALL_APIKEY_TYPES: LlmConnectorType[] = [
  'openai_apikey',
  'anthropic_apikey',
  'openrouter_apikey',
  'xai_apikey',
  'bedrock',
  'azure_openai',
  'gemini_apikey',
];

// Build a DJ policy payload. `allowed_connector_types` is what the server
// computes from the two toggles; the section renders exactly this set.
function makePolicy(
  apikeyEnabled: boolean,
  compatibleEnabled: boolean,
): LlmDjPolicy {
  const allowed: LlmConnectorType[] = [];
  if (apikeyEnabled) allowed.push(...ALL_APIKEY_TYPES);
  if (compatibleEnabled) allowed.push('openai_compatible');
  return {
    llm_apikey_connectors_enabled: apikeyEnabled,
    llm_compatible_connector_enabled: compatibleEnabled,
    allowed_connector_types: allowed,
  };
}

const NOW = new Date().toISOString();

function makeConnector(overrides: Partial<LlmConnector> = {}): LlmConnector {
  return {
    id: 1,
    user_id: 42,
    connector_type: 'openai_apikey',
    display_name: 'My OpenAI',
    status: 'active',
    base_url_plain: null,
    model_hint: 'gpt-5-mini',
    created_at: NOW,
    updated_at: NOW,
    last_used_at: null,
    last_error: null,
    is_default: false,
    ...overrides,
  };
}

describe('AiProvidersSection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the section heading', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));

    render(<AiProvidersSection />);

    expect(screen.getByText('AI / Model providers')).toBeInTheDocument();
  });

  it('lists existing connectors', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({ display_name: 'My OpenAI' }),
      makeConnector({
        id: 2,
        connector_type: 'anthropic_apikey',
        display_name: 'My Claude',
        model_hint: 'claude-haiku',
      }),
    ]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    expect(screen.getByText('My Claude')).toBeInTheDocument();
  });

  it('respects admin policy when filtering allowed connector types', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(false, true));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    // Provider dropdown should only contain the openai_compatible option
    const select = screen.getByLabelText('Provider') as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(['openai_compatible']);
  });

  it('reads the DJ-scoped policy endpoint (not the admin one)', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    const adminPolicySpy = vi
      .spyOn(api, 'getAdminLlmPolicy')
      .mockRejectedValue(new Error('should not be called'));
    const policySpy = vi
      .spyOn(api, 'getLlmPolicy')
      .mockResolvedValue(makePolicy(true, true));

    render(<AiProvidersSection />);

    await waitFor(() => expect(policySpy).toHaveBeenCalled());
    expect(adminPolicySpy).not.toHaveBeenCalled();
  });

  it('fails closed: hides all provider types when policy fetch fails', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    // Simulate the DJ policy endpoint being unavailable.
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('unavailable'));

    render(<AiProvidersSection />);

    // No "+ Add provider" button — the picker is hidden entirely.
    await waitFor(() =>
      expect(
        screen.getByText('Connector creation is currently disabled by admin policy.'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('+ Add provider')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument();
  });

  it('fails closed: only api-key types when compatible is disabled (no leak of all)', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, false));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    const select = screen.getByLabelText('Provider') as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).not.toContain('openai_compatible');
    expect(optionValues).toContain('openai_apikey');
  });

  it('offers Azure OpenAI and reveals its config fields', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, true));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    const select = screen.getByLabelText('Provider') as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain('azure_openai');

    // Switching to Azure surfaces the resource/deployment/api-version inputs.
    fireEvent.change(select, { target: { value: 'azure_openai' } });
    expect(screen.getByLabelText('API key')).toBeInTheDocument();
    expect(screen.getByLabelText('Resource name')).toBeInTheDocument();
    expect(screen.getByLabelText('Deployment name')).toBeInTheDocument();
    expect(screen.getByLabelText('API version')).toBeInTheDocument();
  });

  it('sends Azure config fields on create', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, true));
    const createSpy = vi
      .spyOn(api, 'createLlmConnector')
      .mockResolvedValue(makeConnector({ connector_type: 'azure_openai' }));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    fireEvent.change(screen.getByLabelText('Provider'), {
      target: { value: 'azure_openai' },
    });
    fireEvent.change(screen.getByLabelText('Display name'), {
      target: { value: 'Venue Azure' },
    });
    fireEvent.change(screen.getByLabelText('API key'), {
      target: { value: 'azure-secret' },
    });
    fireEvent.change(screen.getByLabelText('Resource name'), {
      target: { value: 'venue-co' },
    });
    fireEvent.change(screen.getByLabelText('Deployment name'), {
      target: { value: 'gpt4o-prod' },
    });
    fireEvent.change(screen.getByLabelText('API version'), {
      target: { value: '2024-06-01' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        connector_type: 'azure_openai',
        api_key: 'azure-secret',
        azure_resource_name: 'venue-co',
        azure_deployment_name: 'gpt4o-prod',
        azure_api_version: '2024-06-01',
      }),
    );
  });

  it('offers AWS Bedrock when api-key connectors are enabled', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, false));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    const select = screen.getByLabelText('Provider') as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain('bedrock');
    expect(optionValues).not.toContain('openai_compatible');

    // Selecting Bedrock reveals the four AWS credential inputs.
    fireEvent.change(select, { target: { value: 'bedrock' } });
    expect(screen.getByLabelText('AWS access key ID')).toBeInTheDocument();
    expect(screen.getByLabelText('AWS secret access key')).toBeInTheDocument();
    expect(screen.getByLabelText('AWS region')).toBeInTheDocument();
    expect(screen.getByLabelText('Bedrock model ID')).toBeInTheDocument();
  });

  it('runs Test and surfaces the result', async () => {
    const row = makeConnector();
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([row]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, true));
    const testSpy = vi.spyOn(api, 'testLlmConnector').mockResolvedValue({
      ok: true,
      error_code: null,
      message: null,
    });
    // The refresh after Test re-lists connectors
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([row]);

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith(1);
    });
  });

  it('offers OpenRouter and fetches its model dropdown', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, false));
    const modelsSpy = vi.spyOn(api, 'listOpenRouterModels').mockResolvedValue({
      models: [
        { id: 'openai/gpt-4o-mini', name: 'GPT-4o mini' },
        { id: 'anthropic/claude-3.5-sonnet', name: 'Claude 3.5 Sonnet' },
      ],
    });

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    const select = screen.getByLabelText('Provider') as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain('openrouter_apikey');

    // Switch to OpenRouter — the model catalogue should be fetched and rendered.
    fireEvent.change(select, { target: { value: 'openrouter_apikey' } });
    await waitFor(() => expect(modelsSpy).toHaveBeenCalled());

    // The dropdown options appear once the (async) fetch resolves.
    await screen.findByRole('option', { name: /GPT-4o mini/ });
    const modelSelect = screen.getByLabelText('Model (optional)') as HTMLSelectElement;
    const modelValues = Array.from(modelSelect.options).map((o) => o.value);
    expect(modelValues).toContain('openai/gpt-4o-mini');
    expect(modelValues).toContain('anthropic/claude-3.5-sonnet');
  });

  it('creates an OpenRouter connector with the selected model', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getLlmPolicy').mockResolvedValue(makePolicy(true, false));
    vi.spyOn(api, 'listOpenRouterModels').mockResolvedValue({
      models: [{ id: 'openai/gpt-4o-mini', name: 'GPT-4o mini' }],
    });
    const createSpy = vi.spyOn(api, 'createLlmConnector').mockResolvedValue(
      makeConnector({
        connector_type: 'openrouter_apikey',
        display_name: 'My OpenRouter',
        model_hint: 'openai/gpt-4o-mini',
      }),
    );

    render(<AiProvidersSection />);
    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    fireEvent.change(screen.getByLabelText('Provider'), {
      target: { value: 'openrouter_apikey' },
    });
    fireEvent.change(screen.getByLabelText('Display name'), {
      target: { value: 'My OpenRouter' },
    });
    fireEvent.change(screen.getByLabelText('API key'), {
      target: { value: 'sk-or-v1-1234567890abcdef1234567890abcdef' },
    });

    await screen.findByRole('option', { name: /GPT-4o mini/ });
    const modelSelect = screen.getByLabelText('Model (optional)') as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: 'openai/gpt-4o-mini' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        connector_type: 'openrouter_apikey',
        display_name: 'My OpenRouter',
        api_key: 'sk-or-v1-1234567890abcdef1234567890abcdef',
        base_url: null,
        bearer: null,
        model_hint: 'openai/gpt-4o-mini',
      }),
    );
  });

  // ---------- per-DJ default (issue #336) ----------

  it('shows the Default badge on the pinned connector', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({ id: 1, display_name: 'Pinned', is_default: true }),
      makeConnector({ id: 2, display_name: 'Other', is_default: false }),
    ]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('Pinned')).toBeInTheDocument());
    // The badge is rendered next to the display name.
    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  it('clicking the radio on an unpinned connector calls setDefault', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({ id: 1, display_name: 'A', is_default: true }),
      makeConnector({ id: 2, display_name: 'B', is_default: false }),
    ]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));
    const setSpy = vi
      .spyOn(api, 'setLlmConnectorDefault')
      .mockResolvedValue(
        makeConnector({ id: 2, display_name: 'B', is_default: true }),
      );

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('B')).toBeInTheDocument());
    // The radio for connector B is unchecked; click to pin it.
    const radioB = screen.getByLabelText('Set as default');
    fireEvent.click(radioB);

    await waitFor(() => expect(setSpy).toHaveBeenCalledWith(2));
  });

  it('clicking Unpin on the pinned connector calls unsetDefault', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({ id: 1, display_name: 'A', is_default: true }),
    ]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));
    const unsetSpy = vi
      .spyOn(api, 'unsetLlmConnectorDefault')
      .mockResolvedValue(makeConnector({ id: 1, display_name: 'A', is_default: false }));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('A')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Unpin' }));

    await waitFor(() => expect(unsetSpy).toHaveBeenCalledWith(1));
  });

  it('disables the radio on inactive connectors', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({
        id: 1,
        display_name: 'Broken',
        status: 'auth_invalid',
        is_default: false,
      }),
    ]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('Broken')).toBeInTheDocument());
    const radio = screen.getByLabelText('Set as default') as HTMLInputElement;
    expect(radio).toBeDisabled();
  });

  it('optimistically clears the previous default when pinning a new one', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([
      makeConnector({ id: 1, user_id: 42, display_name: 'A', is_default: true }),
      makeConnector({ id: 2, user_id: 42, display_name: 'B', is_default: false }),
    ]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('forbidden'));
    vi.spyOn(api, 'setLlmConnectorDefault').mockResolvedValue(
      makeConnector({ id: 2, user_id: 42, display_name: 'B', is_default: true }),
    );

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('B')).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText('Set as default'));

    // After the optimistic update, the Default badge should sit next to B, not A.
    await waitFor(() => {
      const badge = screen.getByText('Default');
      // Badge is right beside the display name — walk up to the card.
      const card = badge.closest('.card');
      expect(card?.textContent).toContain('B');
    });
  });

  it('deletes after confirmation', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([makeConnector()]);
    vi.spyOn(api, 'getLlmPolicy').mockRejectedValue(new Error('nope'));
    const delSpy = vi.spyOn(api, 'deleteLlmConnector').mockResolvedValue();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(delSpy).toHaveBeenCalledWith(1));
  });
});
