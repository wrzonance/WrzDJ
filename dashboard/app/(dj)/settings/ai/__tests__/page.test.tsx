import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import SettingsAIPage from '../page';
import { api } from '@/lib/api';
import type { LlmConnector } from '@/lib/api-types';

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    role: 'dj',
    logout: vi.fn(),
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/settings/ai',
}));

vi.mock('next/link', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

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
    ...overrides,
  };
}

describe('SettingsAIPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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
    vi.spyOn(api, 'getAdminLlmPolicy').mockRejectedValue(new Error('forbidden'));

    render(<SettingsAIPage />);

    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    expect(screen.getByText('My Claude')).toBeInTheDocument();
  });

  it('respects admin policy when filtering allowed connector types', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: false,
      llm_compatible_connector_enabled: true,
      llm_default_connector_id: null,
    });

    render(<SettingsAIPage />);

    await waitFor(() => expect(screen.getByText('+ Add provider')).toBeInTheDocument());
    fireEvent.click(screen.getByText('+ Add provider'));

    // Provider dropdown should only contain the openai_compatible option
    const select = screen.getByLabelText('Provider') as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(['openai_compatible']);
  });

  it('runs Test and surfaces the result', async () => {
    const row = makeConnector();
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([row]);
    vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: true,
      llm_compatible_connector_enabled: true,
      llm_default_connector_id: null,
    });
    const testSpy = vi.spyOn(api, 'testLlmConnector').mockResolvedValue({
      ok: true,
      error_code: null,
      message: null,
    });
    // The refresh after Test re-lists connectors
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([row]);

    render(<SettingsAIPage />);

    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith(1);
    });
  });

  it('deletes after confirmation', async () => {
    vi.spyOn(api, 'listLlmConnectors').mockResolvedValue([makeConnector()]);
    vi.spyOn(api, 'getAdminLlmPolicy').mockRejectedValue(new Error('nope'));
    const delSpy = vi.spyOn(api, 'deleteLlmConnector').mockResolvedValue();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<SettingsAIPage />);

    await waitFor(() => expect(screen.getByText('My OpenAI')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(delSpy).toHaveBeenCalledWith(1));
  });
});
