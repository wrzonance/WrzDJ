import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AdminAISettingsPage from '../page';
import { api } from '@/lib/api';

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    role: 'admin',
    logout: vi.fn(),
  }),
}));

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: vi.fn(),
    registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []),
    startOnboarding: vi.fn(),
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/admin/ai',
}));

describe('AdminAISettingsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders loading state initially', () => {
    vi.spyOn(api, 'getAISettings').mockImplementation(() => new Promise(() => {}));
    vi.spyOn(api, 'getAIModels').mockImplementation(() => new Promise(() => {}));

    render(<AdminAISettingsPage />);
    expect(screen.getByText('Loading AI settings...')).toBeInTheDocument();
  });

  it('renders settings after load', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({
      models: [
        { id: 'claude-haiku-4-5-20251001', name: 'Claude Haiku 4.5' },
        { id: 'claude-sonnet-4-5-20250929', name: 'Claude Sonnet 4.5' },
      ],
    });

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('AI / LLM Settings')).toBeInTheDocument();
    });

    expect(screen.getByText('Configured')).toBeInTheDocument();
    expect(screen.getByText('...abcd')).toBeInTheDocument();
  });

  it('shows not configured badge when no API key', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: false,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: false,
      api_key_masked: 'Not configured',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({ models: [] });

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Not Configured')).toBeInTheDocument();
    });
  });

  it('calls updateAISettings on save', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({
      models: [{ id: 'claude-haiku-4-5-20251001', name: 'Claude Haiku 4.5' }],
    });
    const updateSpy = vi.spyOn(api, 'updateAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Save Settings')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalled();
    });
  });

  it('shows error on fetch failure', async () => {
    vi.spyOn(api, 'getAISettings').mockRejectedValue(new Error('Network error'));
    vi.spyOn(api, 'getAIModels').mockRejectedValue(new Error('Network error'));

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load AI settings')).toBeInTheDocument();
    });
  });

  it('renders connector policy + per-DJ connector cards when gateway data loads', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({
      models: [{ id: 'claude-haiku-4-5-20251001', name: 'Claude Haiku 4.5' }],
    });
    vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: true,
      llm_compatible_connector_enabled: true,
      llm_default_connector_id: null,
    });
    vi.spyOn(api, 'listAllLlmConnectors').mockResolvedValue([
      {
        id: 1,
        user_id: 42,
        dj_username: 'someDJ',
        connector_type: 'openai_apikey',
        display_name: 'My OpenAI',
        status: 'active',
        base_url_plain: null,
        model_hint: 'gpt-5-mini',
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
        last_used_at: null,
        last_error: null,
      },
    ]);
    vi.spyOn(api, 'getAdminLlmUsage').mockResolvedValue({
      days: 30,
      rows: [],
    });

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Connector policy')).toBeInTheDocument(),
    );
    expect(screen.getByText('Per-DJ connectors')).toBeInTheDocument();
    expect(screen.getByText('someDJ')).toBeInTheDocument();
    expect(screen.getByText(/Usage — last 30 days/)).toBeInTheDocument();
  });

  it('renders the audit trail card with seeded events', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({ models: [] });
    vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: true,
      llm_compatible_connector_enabled: true,
      llm_default_connector_id: null,
    });
    vi.spyOn(api, 'listAllLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getAdminLlmUsage').mockResolvedValue({ days: 30, rows: [] });
    vi.spyOn(api, 'getAdminLlmAudit').mockResolvedValue({
      rows: [
        {
          id: 1,
          created_at: '2026-05-20T12:00:00Z',
          event_type: 'connector_created',
          actor_user_id: 42,
          actor_username: 'someDJ',
          target_connector_id: 7,
          target_connector_display_name: 'My OpenAI',
          notes: null,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Audit trail')).toBeInTheDocument(),
    );
    expect(screen.getByText('connector_created')).toBeInTheDocument();
    expect(screen.getByText('My OpenAI')).toBeInTheDocument();
    // someDJ appears in the audit row (no connectors table rows to collide)
    expect(screen.getByText('someDJ')).toBeInTheDocument();
    // Filter + export controls
    expect(screen.getByLabelText('Event type')).toBeInTheDocument();
    expect(screen.getByText('Export CSV')).toBeInTheDocument();
  });

  it('refetches audit events when the event-type filter changes', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({ models: [] });
    vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: true,
      llm_compatible_connector_enabled: true,
      llm_default_connector_id: null,
    });
    vi.spyOn(api, 'listAllLlmConnectors').mockResolvedValue([]);
    vi.spyOn(api, 'getAdminLlmUsage').mockResolvedValue({ days: 30, rows: [] });
    const auditSpy = vi.spyOn(api, 'getAdminLlmAudit').mockResolvedValue({
      rows: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    const exportSpy = vi
      .spyOn(api, 'downloadAdminLlmAuditCsv')
      .mockResolvedValue(new Blob(['ok'], { type: 'text/csv' }));
    // jsdom doesn't implement these — handleExportCsv triggers a browser download.
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('Audit trail')).toBeInTheDocument());
    auditSpy.mockClear();

    fireEvent.change(screen.getByLabelText('Event type'), {
      target: { value: 'connector_credentials_rotated' },
    });

    await waitFor(() =>
      expect(auditSpy).toHaveBeenCalledWith(
        expect.objectContaining({ event_type: 'connector_credentials_rotated' }),
      ),
    );

    // CSV export must honor the active event-type filter.
    fireEvent.click(screen.getByText('Export CSV'));
    await waitFor(() =>
      expect(exportSpy).toHaveBeenCalledWith(
        expect.objectContaining({ event_type: 'connector_credentials_rotated' }),
      ),
    );

    vi.unstubAllGlobals();
  });

  it('force-revokes a connector via the admin table', async () => {
    vi.spyOn(api, 'getAISettings').mockResolvedValue({
      llm_enabled: true,
      llm_model: 'claude-haiku-4-5-20251001',
      llm_rate_limit_per_minute: 3,
      api_key_configured: true,
      api_key_masked: '...abcd',
    });
    vi.spyOn(api, 'getAIModels').mockResolvedValue({ models: [] });
    vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue({
      llm_apikey_connectors_enabled: true,
      llm_compatible_connector_enabled: true,
      llm_default_connector_id: null,
    });
    vi.spyOn(api, 'listAllLlmConnectors').mockResolvedValue([
      {
        id: 9,
        user_id: 42,
        dj_username: 'badDJ',
        connector_type: 'openai_apikey',
        display_name: 'Compromised',
        status: 'active',
        base_url_plain: null,
        model_hint: null,
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
        last_used_at: null,
        last_error: null,
      },
    ]);
    vi.spyOn(api, 'getAdminLlmUsage').mockResolvedValue({ days: 30, rows: [] });
    const revokeSpy = vi.spyOn(api, 'revokeAdminLlmConnector').mockResolvedValue({
      id: 9,
      user_id: 42,
      dj_username: 'badDJ',
      connector_type: 'openai_apikey',
      display_name: 'Compromised',
      status: 'disabled',
      base_url_plain: null,
      model_hint: null,
      created_at: '2026-05-01T00:00:00Z',
      updated_at: '2026-05-01T00:00:00Z',
      last_used_at: null,
      last_error: null,
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('Compromised')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Force-revoke'));
    await waitFor(() => expect(revokeSpy).toHaveBeenCalledWith(9));
  });
});
